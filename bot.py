import requests
import json
import uuid
import sqlite3
import os
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
import nest_asyncio
import re
from money import start_money_worker, stop_money_worker, is_worker_running, get_running_workers
from dotenv import load_dotenv

# Apply nest_asyncio for nested event loops
nest_asyncio.apply()


# Konfigurasi logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bussid_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Baca .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN tidak ditemukan di .env")
    raise ValueError("BOT_TOKEN harus diset di file .env")

# Baca config.json
try:
    with open("config.json", "r") as config_file:
        config = json.load(config_file)
        ADMIN_ID = config["admin_id"]
        DB_NAME = config["db_name"]
        MAX_RUNNING_PER_USER = config["max_running_per_user"]
except FileNotFoundError:
    logger.error("File config.json tidak ditemukan")
    raise FileNotFoundError("File config.json harus ada di direktori bot")
except json.JSONDecodeError:
    logger.error("Format config.json tidak valid")
    raise json.JSONDecodeError("File config.json harus berformat JSON yang valid")
except KeyError as e:
    logger.error(f"Key {e} tidak ditemukan di config.json")
    raise KeyError(f"Key {e} harus ada di config.json")
    
# Inisialisasi database
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                session_ticket TEXT NOT NULL,
                payload TEXT NOT NULL,
                device_id TEXT NOT NULL,
                telegram_id INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS whitelist (
                telegram_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                whitelist_time TEXT NOT NULL
            )
        """)
        conn.commit()

def is_whitelisted(telegram_id, conn):
    c = conn.cursor()
    c.execute("SELECT telegram_id FROM whitelist WHERE telegram_id = ?", (telegram_id,))
    return c.fetchone() is not None or telegram_id == ADMIN_ID

def get_user_running_count(telegram_id):
    running_accounts = get_running_workers()
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM accounts WHERE telegram_id = ?", (telegram_id,))
        user_accounts = [row[0] for row in c.fetchall()]
        return len([acc for acc in running_accounts if acc in user_accounts])

def generate_device_id():
    return str(uuid.uuid4()).replace("-", "")[:16]

def create_bussid_account(display_name):
    url = "https://4ae9.playfabapi.com/Client/LoginWithAndroidDeviceID"
    headers = {
        "User-Agent": "UnityEngine-Unity; Version: 2018.4.26f1",
        "X-ReportErrorAsSuccess": "true",
        "X-PlayFabSDK": "UnitySDK-2.20.170411",
        "Content-Type": "application/json"
    }
    device_id = generate_device_id()
    payload = {
        "AndroidDeviceId": device_id,
        "OS": "Android",
        "AndroidDevice": "AndroidPhone",
        "CreateAccount": True,
        "TitleId": "4AE9",
        "EncryptedRequest": None,
        "PlayerSecret": None,
        "InfoRequestParameters": None
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        logger.info(f"Create account response: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 200:
                return data["data"]["SessionTicket"], payload, device_id, ""
            return "", "", "", f"Error: {data.get('errorMessage', 'Unknown error')}"
        return "", "", "", f"HTTP Error: {response.status_code}"
    except Exception as e:
        logger.error(f"Create account error: {str(e)}")
        return "", "", "", f"Error: {str(e)}"

def update_display_name(session_ticket, display_name):
    url = "https://4ae9.playfabapi.com/Client/UpdateUserTitleDisplayName"
    headers = {
        "User-Agent": "UnityEngine-Unity; Version: 2018.4.26f1",
        "X-ReportErrorAsSuccess": "true",
        "X-PlayFabSDK": "UnitySDK-2.20.170411",
        "X-Authorization": session_ticket,
        "Content-Type": "application/json"
    }
    payload = {"DisplayName": display_name}
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        logger.info(f"Update display name response: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 200:
                return True, ""
            return False, f"Error: {data.get('errorMessage', 'Unknown error')}"
        return False, f"HTTP Error: {response.status_code}"
    except Exception as e:
        logger.error(f"Update display name error: {str(e)}")
        return False, f"Error: {str(e)}"

def get_player_info(session_ticket):
    url = "https://4ae9.playfabapi.com/Client/GetPlayerCombinedInfo"
    headers = {
        "User-Agent": "UnityEngine-Unity; Version: 2018.4.26f1",
        "X-ReportErrorAsSuccess": "true",
        "X-PlayFabSDK": "UnitySDK-2.20.170411",
        "X-Authorization": session_ticket,
        "Content-Type": "application/json"
    }
    payload = {
        "PlayFabId": None,
        "InfoRequestParameters": {
            "GetUserAccountInfo": True,
            "GetUserInventory": True,
            "GetUserVirtualCurrency": True,
            "GetUserData": False,
            "GetUserReadOnlyData": True,
            "GetCharacterList": False,
            "GetTitleData": True,
            "GetPlayerStatistics": False
        }
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        logger.info(f"Get player info response: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 200:
                info = data["data"]["InfoResultPayload"]
                account_info = info["AccountInfo"]
                virtual_currency = info.get("UserVirtualCurrency", {})
                return {
                    "PlayFabId": account_info["PlayFabId"],
                    "DisplayName": account_info["TitleInfo"]["DisplayName"],
                    "Origination": account_info["TitleInfo"]["Origination"],
                    "Created": account_info["TitleInfo"]["Created"],
                    "LastLogin": account_info["TitleInfo"]["LastLogin"],
                    "FirstLogin": account_info["TitleInfo"]["FirstLogin"],
                    "UserVirtualCurrency": virtual_currency
                }, "", session_ticket
            return None, f"Error: {data.get('errorMessage', 'Unknown error')}", session_ticket
        return None, f"HTTP Error: {response.status_code}", session_ticket
    except Exception as e:
        logger.error(f"Get player info error: {str(e)}")
        return None, f"Error: {str(e)}", session_ticket

def generate_account_file(session_ticket, payload, display_name):
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', display_name)
    filename = f"bussid_{safe_name}.txt"
    content = (
        f"X-Authorization: {session_ticket}\n"
        f"{json.dumps(json.loads(payload), indent=2)}\n"
        f"Nama akun: {display_name}"
    )
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        return filename, ""
    except Exception as e:
        logger.error(f"Generate file error: {str(e)}")
        return None, f"Error: {str(e)}"

async def show_main_menu(update, context, chat_id):
    keyboard = [
        ["➕ Add Account", "🆕 Create Account"],
        ["🗑 Delete Account", "📋 List Accounts"],
        ["💰 Add Money"]
    ]
    if update.effective_user.id == ADMIN_ID:
        keyboard.append(["🔐 Admin Menu"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await context.bot.send_message(chat_id=chat_id, text="🎮 Selamat datang di BUSSID Bot! Pilih menu:", reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with sqlite3.connect(DB_NAME) as conn:
        if not is_whitelisted(user_id, conn):
            await update.message.reply_text("🚫 Maaf, kamu tidak diizinkan menggunakan bot ini.", reply_markup=ReplyKeyboardRemove())
            return
    context.user_data.clear()
    await show_main_menu(update, context, update.effective_chat.id)

async def show_account_info(update, context, account_name, session_ticket, payload, refresh=False):
    user_id = update.effective_user.id
    info = None
    error = ""
    
    if refresh:
        logger.info(f"Refreshing account: {account_name}")
        info, error, new_session_ticket = get_player_info(session_ticket)
        if info:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                query = "UPDATE accounts SET session_ticket = ? WHERE name = ? AND telegram_id = ?" if user_id != ADMIN_ID else "UPDATE accounts SET session_ticket = ? WHERE name = ?"
                c.execute(query, (new_session_ticket, account_name, user_id) if user_id != ADMIN_ID else (new_session_ticket, account_name))
                conn.commit()
            session_ticket = new_session_ticket
        else:
            logger.error(f"Refresh failed for {account_name}: {error}")
            await update.message.reply_text(f"⚠ Gagal refresh: {error}", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            return
    else:
        info, error, _ = get_player_info(session_ticket)
    
    payload_formatted = json.dumps(json.loads(payload), indent=2)
    message = ""
    
    if info:
        vc = json.dumps(info["UserVirtualCurrency"]) if info["UserVirtualCurrency"] else "{}"
        message += (
            "🔥 Info Akun Keren 🔥\n"
            f"🆔 PlayFabId: {info['PlayFabId']}\n"
            f"📛 DisplayName: {info['DisplayName']}\n"
            f"📅 Created: {info['Created']}\n"
            f"⏰ LastLogin: {info['LastLogin']}\n"
            f"💰 VirtualCurrency: {vc}\n\n"
        )
    else:
        message += f"⚠ Gagal ambil info akun: {error}\n\n"
    
    message += (
        "📋 Payload:\n"
        f"```\n{payload_formatted}\n```\n"
        "🔑 Auth:\n"
        f"```\n{session_ticket}\n```"
    )
    
    keyboard = [["🔄 Change Name BUSSID", "📄 File Txt"], ["🔄 Refresh"], ["⬅ Kembali"]]
    await update.message.reply_text(message, parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    state = context.user_data.get("state", "")
    
    with sqlite3.connect(DB_NAME) as conn:
        if not is_whitelisted(user_id, conn):
            await update.message.reply_text("🚫 Maaf, kamu tidak diizinkan menggunakan bot ini.", reply_markup=ReplyKeyboardRemove())
            return
        
        c = conn.cursor()
        
        # Main menu
        if not state:
            if text == "➕ Add Account":
                context.user_data["state"] = "add_account_name"
                context.user_data["prev"] = ""
                await update.message.reply_text("📝 Masukkan nama akun untuk daftar akun:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            elif text == "🆕 Create Account":
                context.user_data["state"] = "create_account_list_name"
                context.user_data["prev"] = ""
                await update.message.reply_text("📝 Masukkan nama akun untuk daftar akun:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            elif text == "🗑 Delete Account":
                context.user_data["state"] = "delete_account"
                context.user_data["prev"] = ""
                query = "SELECT name FROM accounts WHERE telegram_id = ?" if user_id != ADMIN_ID else "SELECT name FROM accounts"
                c.execute(query, (user_id,) if user_id != ADMIN_ID else ())
                accounts = c.fetchall()
                if not accounts:
                    await update.message.reply_text("📭 Tidak ada akun yang tersimpan.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in accounts] + [["⬅ Kembali"]]
                await update.message.reply_text("🗑 Pilih akun untuk dihapus:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif text == "📋 List Accounts":
                context.user_data["state"] = "list_accounts"
                context.user_data["prev"] = ""
                query = "SELECT name FROM accounts WHERE telegram_id = ?" if user_id != ADMIN_ID else "SELECT name FROM accounts"
                c.execute(query, (user_id,) if user_id != ADMIN_ID else ())
                accounts = c.fetchall()
                if not accounts:
                    await update.message.reply_text("📭 Tidak ada akun yang tersimpan.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in accounts] + [["⬅ Kembali"]]
                await update.message.reply_text("📋 Pilih akun untuk detail:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif text == "💰 Add Money":
                context.user_data["state"] = "add_money_select"
                context.user_data["prev"] = ""
                query = "SELECT name FROM accounts WHERE telegram_id = ?" if user_id != ADMIN_ID else "SELECT name FROM accounts"
                c.execute(query, (user_id,) if user_id != ADMIN_ID else ())
                accounts = c.fetchall()
                if not accounts:
                    await update.message.reply_text("📭 Tidak ada akun yang tersimpan.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in accounts] + [["⬅ Kembali"]]
                await update.message.reply_text("💰 Pilih akun untuk Add Money:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif text == "🔐 Admin Menu" and user_id == ADMIN_ID:
                context.user_data["state"] = "admin_menu"
                context.user_data["prev"] = ""
                keyboard = [
                    ["✅ Whitelist User", "❌ Unwhitelist User"],
                    ["📜 List Whitelist", "📊 List Running"],
                    ["⬅ Kembali"]
                ]
                await update.message.reply_text("🔐 Admin Menu:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif text == "🔐 Admin Menu":
                await update.message.reply_text("🚫 Hanya admin yang bisa akses.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            return
        
        # Back navigation
        if text == "⬅ Kembali":
            prev = context.user_data.get("prev", "")
            if prev == "":
                context.user_data.clear()
                await show_main_menu(update, context, chat_id)
            elif prev == "list_accounts":
                context.user_data["state"] = "list_accounts"
                context.user_data["prev"] = ""
                query = "SELECT name FROM accounts WHERE telegram_id = ?" if user_id != ADMIN_ID else "SELECT name FROM accounts"
                c.execute(query, (user_id,) if user_id != ADMIN_ID else ())
                accounts = c.fetchall()
                if not accounts:
                    await update.message.reply_text("📭 Tidak ada akun yang tersimpan.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in accounts] + [["⬅ Kembali"]]
                await update.message.reply_text("📋 Pilih akun untuk detail:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif prev == "add_money_select":
                context.user_data["state"] = "add_money_select"
                context.user_data["prev"] = ""
                query = "SELECT name FROM accounts WHERE telegram_id = ?" if user_id != ADMIN_ID else "SELECT name FROM accounts"
                c.execute(query, (user_id,) if user_id != ADMIN_ID else ())
                accounts = c.fetchall()
                if not accounts:
                    await update.message.reply_text("📭 Tidak ada akun yang tersimpan.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in accounts] + [["⬅ Kembali"]]
                await update.message.reply_text("💰 Pilih akun untuk Add Money:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif prev == "add_money_control":
                context.user_data["state"] = "add_money_select"
                context.user_data["prev"] = ""
                query = "SELECT name FROM accounts WHERE telegram_id = ?" if user_id != ADMIN_ID else "SELECT name FROM accounts"
                c.execute(query, (user_id,) if user_id != ADMIN_ID else ())
                accounts = c.fetchall()
                if not accounts:
                    await update.message.reply_text("📭 Tidak ada akun yang tersimpan.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in accounts] + [["⬅ Kembali"]]
                await update.message.reply_text("💰 Pilih akun untuk Add Money:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif prev == "admin_menu":
                context.user_data["state"] = "admin_menu"
                context.user_data["prev"] = ""
                keyboard = [
                    ["✅ Whitelist User", "❌ Unwhitelist User"],
                    ["📜 List Whitelist", "📊 List Running"],
                    ["⬅ Kembali"]
                ]
                await update.message.reply_text("🔐 Admin Menu:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif prev == "list_running_users":
                context.user_data["state"] = "admin_menu"
                context.user_data["prev"] = ""
                keyboard = [
                    ["✅ Whitelist User", "❌ Unwhitelist User"],
                    ["📜 List Whitelist", "📊 List Running"],
                    ["⬅ Kembali"]
                ]
                await update.message.reply_text("🔐 Admin Menu:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif prev == "list_running_accounts":
                context.user_data["state"] = "list_running_users"
                context.user_data["prev"] = "admin_menu"
                c.execute("SELECT name FROM whitelist")
                users = c.fetchall()
                if not users:
                    await update.message.reply_text("📭 Tidak ada user di-whitelist.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in users] + [["⬅ Kembali"]]
                await update.message.reply_text("📊 Pilih user untuk lihat akun running:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            return
        
        # Admin menu
        if state == "admin_menu":
            if text == "✅ Whitelist User":
                context.user_data["state"] = "whitelist_id"
                context.user_data["prev"] = "admin_menu"
                await update.message.reply_text("🆔 Masukkan Telegram ID:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            elif text == "❌ Unwhitelist User":
                context.user_data["state"] = "unwhitelist"
                context.user_data["prev"] = "admin_menu"
                c.execute("SELECT name FROM whitelist")
                users = c.fetchall()
                if not users:
                    await update.message.reply_text("📭 Tidak ada user di-whitelist.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in users] + [["⬅ Kembali"]]
                await update.message.reply_text("❌ Pilih user untuk di-unwhitelist:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif text == "📜 List Whitelist":
                context.user_data["state"] = "list_whitelist"
                context.user_data["prev"] = "admin_menu"
                c.execute("SELECT name FROM whitelist")
                users = c.fetchall()
                if not users:
                    await update.message.reply_text("📭 Tidak ada user di-whitelist.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in users] + [["⬅ Kembali"]]
                await update.message.reply_text("📜 Pilih user untuk detail:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            elif text == "📊 List Running":
                context.user_data["state"] = "list_running_users"
                context.user_data["prev"] = "admin_menu"
                c.execute("SELECT name FROM whitelist")
                users = c.fetchall()
                if not users:
                    await update.message.reply_text("📭 Tidak ada user di-whitelist.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    return
                keyboard = [[name[0]] for name in users] + [["⬅ Kembali"]]
                await update.message.reply_text("📊 Pilih user untuk lihat akun running:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            return
        
        # List accounts
        if state == "list_accounts":
            query = "SELECT name, session_ticket, payload FROM accounts WHERE name = ? AND telegram_id = ?" if user_id != ADMIN_ID else "SELECT name, session_ticket, payload FROM accounts WHERE name = ?"
            c.execute(query, (text, user_id) if user_id != ADMIN_ID else (text,))
            result = c.fetchone()
            if result:
                account_name, session_ticket, payload = result
                context.user_data["current_account"] = account_name
                context.user_data["state"] = "account_info"
                context.user_data["prev"] = "list_accounts"
                await show_account_info(update, context, account_name, session_ticket, payload)
            else:
                await update.message.reply_text("🚫 Akun tidak ditemukan atau bukan milikmu.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            return
        
        # Account info options
        if state == "account_info":
            account_name = context.user_data.get("current_account")
            query = "SELECT session_ticket, payload FROM accounts WHERE name = ? AND telegram_id = ?" if user_id != ADMIN_ID else "SELECT session_ticket, payload FROM accounts WHERE name = ?"
            c.execute(query, (account_name, user_id) if user_id != ADMIN_ID else (account_name,))
            result = c.fetchone()
            if result:
                session_ticket, payload = result
                if text == "🔄 Change Name BUSSID":
                    context.user_data["state"] = "change_bussid_name"
                    context.user_data["prev"] = "list_accounts"
                    await update.message.reply_text("📛 Masukkan nama BUSSID baru:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                elif text == "📄 File Txt":
                    filename, error = generate_account_file(session_ticket, payload, account_name)
                    if filename:
                        with open(filename, "rb") as f:
                            await update.message.reply_document(document=f, filename=filename)
                        os.remove(filename)
                        await update.message.reply_text("✅ File dikirim.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                    else:
                        await update.message.reply_text(f"⚠ Gagal membuat file: {error}", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                elif text == "🔄 Refresh":
                    await show_account_info(update, context, account_name, session_ticket, payload, refresh=True)
            else:
                await update.message.reply_text("🚫 Akun tidak ditemukan atau bukan milikmu.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            return
        
        # Delete account
        if state == "delete_account":
            query = "DELETE FROM accounts WHERE name = ? AND telegram_id = ?" if user_id != ADMIN_ID else "DELETE FROM accounts WHERE name = ?"
            c.execute(query, (text, user_id) if user_id != ADMIN_ID else (text,))
            if c.rowcount > 0:
                conn.commit()
                stop_money_worker(text)  # Stop worker jika akun dihapus
                await update.message.reply_text(f"✅ Akun '{text}' dihapus.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                logger.info(f"User {user_id} deleted account: {text}")
            else:
                await update.message.reply_text("🚫 Akun tidak ditemukan atau bukan milikmu.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            context.user_data.clear()
            await show_main_menu(update, context, chat_id)
            return
        
        # Add account
        if state == "add_account_name":
            if not text:
                await update.message.reply_text("📝 Nama akun tidak boleh kosong:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                return
            context.user_data["add_name"] = text
            context.user_data["state"] = "add_account_auth"
            await update.message.reply_text("🔑 Masukkan X-Authorization:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
        
        elif state == "add_account_auth":
            if not text:
                await update.message.reply_text("🔑 SessionTicket tidak boleh kosong:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                return
            session_ticket = text
            display_name = context.user_data.get("add_name", "")
            
            info, error = get_player_info(session_ticket)[:2]
            if not info:
                await update.message.reply_text(f"⚠ Gagal validasi: {error}", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                context.user_data.clear()
                await show_main_menu(update, context, chat_id)
                return
            
            c.execute("SELECT name FROM accounts WHERE name = ?", (display_name,))
            if c.fetchone():
                await update.message.reply_text(f"🚫 Nama '{display_name}' sudah ada.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                return
            
            payload = {
                "AndroidDeviceId": "manual",
                "OS": "Android",
                "AndroidDevice": "AndroidPhone",
                "CreateAccount": True,
                "TitleId": "4AE9",
                "EncryptedRequest": None,
                "PlayerSecret": None,
                "InfoRequestParameters": None
            }
            c.execute(
                "INSERT INTO accounts (name, session_ticket, payload, device_id, telegram_id) VALUES (?, ?, ?, ?, ?)",
                (display_name, session_ticket, json.dumps(payload), "manual", user_id)
            )
            conn.commit()
            
            await update.message.reply_text(f"✅ Akun '{display_name}' ditambahkan.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            logger.info(f"User {user_id} added account: {display_name}")
            context.user_data.clear()
            await show_main_menu(update, context, chat_id)
        
        # Create account
        if state == "create_account_list_name":
            if not text:
                await update.message.reply_text("📝 Nama akun tidak boleh kosong:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                return
            context.user_data["list_name"] = text
            context.user_data["state"] = "create_account_bussid_name"
            await update.message.reply_text("📛 Masukkan nama BUSSID:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
        
        elif state == "create_account_bussid_name":
            if not text:
                await update.message.reply_text("📛 Nama BUSSID tidak boleh kosong:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                return
            list_name = context.user_data.get("list_name", "")
            bussid_name = text
            await update.message.reply_text("⏳ Membuat akun BUSSID...")
            
            session_ticket, payload, device_id, error = create_bussid_account(bussid_name)
            if not session_ticket:
                await update.message.reply_text(f"⚠ Gagal membuat akun: {error}", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                context.user_data.clear()
                await show_main_menu(update, context, chat_id)
                return
            
            await update.message.reply_text(
                f"📋 Payload:\n"
                f"```\n{json.dumps(payload, indent=2)}\n```\n"
                f"🔑 Auth:\n"
                f"```\n{session_ticket}\n```",
                parse_mode="Markdown"
            )
            await update.message.reply_text("📝 Mengganti nama BUSSID...")
            
            success, error = update_display_name(session_ticket, bussid_name)
            if not success:
                await update.message.reply_text(f"⚠ Gagal ganti nama: {error}", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                context.user_data.clear()
                await show_main_menu(update, context, chat_id)
                return
            
            c.execute("SELECT name FROM accounts WHERE name = ?", (list_name,))
            if c.fetchone():
                await update.message.reply_text(f"🚫 Nama '{list_name}' sudah ada.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                context.user_data.clear()
                await show_main_menu(update, context, chat_id)
                return
            
            c.execute(
                "INSERT INTO accounts (name, session_ticket, payload, device_id, telegram_id) VALUES (?, ?, ?, ?, ?)",
                (list_name, session_ticket, json.dumps(payload), device_id, user_id)
            )
            conn.commit()
            
            await update.message.reply_text(f"✅ Akun '{list_name}' (BUSSID: {bussid_name}) dibuat.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            logger.info(f"User {user_id} created account: {list_name}")
            context.user_data.clear()
            await show_main_menu(update, context, chat_id)
        
        # Change BUSSID name
        if state == "change_bussid_name":
            if not text:
                await update.message.reply_text("📛 Nama BUSSID tidak boleh kosong:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                return
            account_name = context.user_data.get("current_account", "")
            query = "SELECT session_ticket FROM accounts WHERE name = ? AND telegram_id = ?" if user_id != ADMIN_ID else "SELECT session_ticket FROM accounts WHERE name = ?"
            c.execute(query, (account_name, user_id) if user_id != ADMIN_ID else (account_name,))
            result = c.fetchone()
            if result:
                session_ticket = result[0]
                success, error = update_display_name(session_ticket, text)
                if success:
                    await update.message.reply_text(f"✅ Nama BUSSID untuk '{account_name}' diubah jadi '{text}'.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                else:
                    await update.message.reply_text(f"⚠ Gagal ganti nama: {error}", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            else:
                await update.message.reply_text("🚫 Akun tidak ditemukan atau bukan milikmu.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            context.user_data.clear()
            await show_main_menu(update, context, chat_id)
        
        # Add Money select account
        elif state == "add_money_select":
            query = "SELECT name, session_ticket FROM accounts WHERE name = ? AND telegram_id = ?" if user_id != ADMIN_ID else "SELECT name, session_ticket FROM accounts WHERE name = ?"
            c.execute(query, (text, user_id) if user_id != ADMIN_ID else (text,))
            result = c.fetchone()
            if result:
                account_name, session_ticket = result
                context.user_data["current_account"] = account_name
                context.user_data["session_ticket"] = session_ticket
                context.user_data["state"] = "add_money_control"
                context.user_data["prev"] = "add_money_select"
                status = "🟢 Sedang Berjalan" if is_worker_running(account_name) else "🔴 Stop"
                message = (
                    f"💰 Kontrol Add Money untuk '{account_name}':\n"
                    f"Status: {status}"
                )
                keyboard = [["▶ Start", "⏹ Stop"], ["⬅ Kembali"]]
                await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            else:
                await update.message.reply_text("🚫 Akun tidak ditemukan atau bukan milikmu.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            return
        
        # Add Money control
        elif state == "add_money_control":
            account_name = context.user_data.get("current_account", "")
            session_ticket = context.user_data.get("session_ticket", "")
            if text == "▶ Start":
                if user_id != ADMIN_ID:  # Cek limit untuk non-admin
                    running_count = get_user_running_count(user_id)
                    if running_count >= MAX_RUNNING_PER_USER:
                        await update.message.reply_text(
                            f"⚠ Kamu sudah menjalankan {MAX_RUNNING_PER_USER} akun. Stop salah satu dulu!",
                            reply_markup=ReplyKeyboardMarkup([["▶ Start", "⏹ Stop"], ["⬅ Kembali"]], resize_keyboard=True)
                        )
                        return
                if start_money_worker(account_name, session_ticket):
                    await update.message.reply_text(
                        f"✅ Add Money untuk '{account_name}' dimulai.",
                        reply_markup=ReplyKeyboardMarkup([["▶ Start", "⏹ Stop"], ["⬅ Kembali"]], resize_keyboard=True)
                    )
                    logger.info(f"User {user_id} started Add Money: {account_name}")
                else:
                    await update.message.reply_text(
                        f"⚠ Add Money untuk '{account_name}' sudah berjalan.",
                        reply_markup=ReplyKeyboardMarkup([["▶ Start", "⏹ Stop"], ["⬅ Kembali"]], resize_keyboard=True)
                    )
            elif text == "⏹ Stop":
                if stop_money_worker(account_name):
                    await update.message.reply_text(
                        f"✅ Add Money untuk '{account_name}' dihentikan.",
                        reply_markup=ReplyKeyboardMarkup([["▶ Start", "⏹ Stop"], ["⬅ Kembali"]], resize_keyboard=True)
                    )
                    logger.info(f"User {user_id} stopped Add Money: {account_name}")
                else:
                    await update.message.reply_text(
                        f"⚠ Add Money untuk '{account_name}' tidak berjalan.",
                        reply_markup=ReplyKeyboardMarkup([["▶ Start", "⏹ Stop"], ["⬅ Kembali"]], resize_keyboard=True)
                    )
            return
        
        # List running users
        if state == "list_running_users":
            c.execute("SELECT telegram_id FROM whitelist WHERE name = ?", (text,))
            result = c.fetchone()
            if result:
                telegram_id = result[0]
                context.user_data["selected_user_id"] = telegram_id
                context.user_data["selected_user_name"] = text
                context.user_data["state"] = "list_running_accounts"
                context.user_data["prev"] = "list_running_users"
                
                # Ambil akun running milik user ini
                running_accounts = get_running_workers()
                c.execute("SELECT name FROM accounts WHERE telegram_id = ?", (telegram_id,))
                user_accounts = [row[0] for row in c.fetchall()]
                running_user_accounts = [acc for acc in running_accounts if acc in user_accounts]
                
                if not running_user_accounts:
                    await update.message.reply_text(
                        f"📭 Tidak ada akun running untuk user '{text}'.",
                        reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True)
                    )
                    return
                
                keyboard = [[acc] for acc in running_user_accounts] + [["⬅ Kembali"]]
                await update.message.reply_text(
                    f"📊 Akun running untuk user '{text}':",
                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                )
            else:
                await update.message.reply_text(
                    "🚫 User tidak ditemukan.",
                    reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True)
                )
            return
        
        # List running accounts
        if state == "list_running_accounts":
            running_accounts = get_running_workers()
            if text in running_accounts:
                context.user_data["current_account"] = text
                context.user_data["state"] = "running_control"
                context.user_data["prev"] = "list_running_accounts"
                await update.message.reply_text(
                    f"📽 Kontrol running untuk '{text}':",
                    reply_markup=ReplyKeyboardMarkup([["⏹ Stop"], ["⬅ Kembali"]], resize_keyboard=True)
                )
            else:
                await update.message.reply_text(
                    "🚫 Akun tidak valid atau tidak running.",
                    reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True)
                )
            return
        
        # Running control
        if state == "running_control":
            account_name = context.user_data.get("current_account", "")
            if text == "⏹ Stop":
                if stop_money_worker(account_name):
                    await update.message.reply_text(
                        f"✅ Add Money untuk '{account_name}' dihentikan.",
                        reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True)
                    )
                    logger.info(f"Admin {user_id} stopped Add Money: {account_name}")
                else:
                    await update.message.reply_text(
                        f"⚠ Add Money untuk '{account_name}' tidak berjalan.",
                        reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True)
                    )
                context.user_data["state"] = "list_running_accounts"
                context.user_data["prev"] = "list_running_users"
                telegram_id = context.user_data.get("selected_user_id", 0)
                user_name = context.user_data.get("selected_user_name", "")
                
                running_accounts = get_running_workers()
                c.execute("SELECT name FROM accounts WHERE telegram_id = ?", (telegram_id,))
                user_accounts = [row[0] for row in c.fetchall()]
                running_user_accounts = [acc for acc in running_accounts if acc in user_accounts]
                
                if not running_user_accounts:
                    await update.message.reply_text(
                        f"📭 Tidak ada akun running untuk user '{user_name}'.",
                        reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True)
                    )
                    return
                
                keyboard = [[acc] for acc in running_user_accounts] + [["⬅ Kembali"]]
                await update.message.reply_text(
                    f"📊 Akun running untuk user '{user_name}':",
                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                )
            return
        
        # Whitelist
        if state == "whitelist_id":
            try:
                telegram_id = int(text)
            except ValueError:
                await update.message.reply_text("🆔 ID harus angka:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                return
            context.user_data["whitelist_id"] = telegram_id
            context.user_data["state"] = "whitelist_name"
            await update.message.reply_text("📛 Masukkan nama user:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
        
        elif state == "whitelist_name":
            if not text:
                await update.message.reply_text("📛 Nama tidak boleh kosong:", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                return
            telegram_id = context.user_data.get("whitelist_id", 0)
            
            c.execute("SELECT telegram_id FROM whitelist WHERE telegram_id = ?", (telegram_id,))
            if c.fetchone():
                await update.message.reply_text(f"🚫 User ID {telegram_id} sudah di-whitelist.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                context.user_data.clear()
                await show_main_menu(update, context, chat_id)
                return
            
            whitelist_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO whitelist (telegram_id, name, whitelist_time) VALUES (?, ?, ?)",
                (telegram_id, text, whitelist_time)
            )
            conn.commit()
            
            await update.message.reply_text(f"✅ User '{text}' (ID: {telegram_id}) di-whitelist pada {whitelist_time}.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            logger.info(f"Admin {user_id} whitelisted user: {telegram_id}")
            context.user_data.clear()
            await show_main_menu(update, context, chat_id)
        
        # Unwhitelist
        elif state == "unwhitelist":
            c.execute("SELECT telegram_id FROM whitelist WHERE name = ?", (text,))
            result = c.fetchone()
            if result:
                telegram_id = result[0]
                c.execute("DELETE FROM whitelist WHERE telegram_id = ?", (telegram_id,))
                conn.commit()
                await update.message.reply_text(f"✅ User '{text}' di-unwhitelist.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
                logger.info(f"Admin {user_id} unwhitelisted user: {telegram_id}")
            else:
                await update.message.reply_text("⚠ User tidak ditemukan.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            context.user_data.clear()
            await show_main_menu(update, context, chat_id)
        
        # List whitelist
        elif state == "list_whitelist":
            c.execute("SELECT telegram_id, whitelist_time FROM whitelist WHERE name = ?", (text,))
            result = c.fetchone()
            if result:
                telegram_id, whitelist_time = result
                message = (
                    f"ℹ️ Info Whitelist:\n"
                    f"```\n"
                    f"Nama: {text}\n"
                    f"Telegram ID: {telegram_id}\n"
                    f"Waktu Whitelist: {whitelist_time}\n"
                    f"```"
                )
                await update.message.reply_text(message, parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            else:
                await update.message.reply_text("⚠ User tidak ditemukan.", reply_markup=ReplyKeyboardMarkup([["⬅ Kembali"]], resize_keyboard=True))
            context.user_data.clear()
            await show_main_menu(update, context, chat_id)

async def reset_webhook(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.deleteWebhook(drop_pending_updates=True)
        logger.info("Webhook deleted and pending updates dropped.")
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")

async def main():
    try:
        init_db()
        app = Application.builder().token(BOT_TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        if app.job_queue:
            app.job_queue.run_once(reset_webhook, 0)
        else:
            await reset_webhook(app)
        
        logger.info("Starting Telegram bot.")
        await app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Bot start error: {str(e)}")
        raise

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()