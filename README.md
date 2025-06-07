
# Bot Telegram Bussid

Bot telegram game bussid dengan fitur yang menarik dengan sistem python
## Authors

- [@Fortoises](https://www.github.com/Fortoises)

![Python](https://img.shields.io/badge/python-blue)
## Features

### Manage account bussid
- Create account
- Add account
- Delete account
- List Account

### Admin Menu
- Whitelist User menggunakan id telegram
- Unwhitelist user 
- List Whitelist
- List Running
    - Melihat semua akun yang di run
    - Paksa berhenti akun

### Add Money Bussid

Fitur ini bisa menambahkan uang bussid selama 24 jam sebelum user ngestop. Jadi uang bussid akan terus bertambah sampai batas maksimal nya (2M)

### Untuk Free User maksimal ngejalanin 2 akun sekaligus
## Installation

### Requirement

- Python 3.7+ (Pydroid 3 di Android biasanya udah include Python 3.8+).
- Telegram Bot Token dari @BotFather.
- Telegram ID untuk admin (bisa dicek via bot seperti @userinfobot).
- Akses storage di Android (untuk Pydroid 3) atau izin read/write di Linux/Windows.



```bash
git clone https://github.com/username/bussid-bot.git
cd bussid-bot    
```
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 
```

```bash
pip install python-telegram-bot==20.7 requests python-dotenv
```

### Konfigurasi

#### config.json

```json
{
  "admin_id": 123456789,
  "db_name": "bussid_accounts.db",
  "max_running_per_user": 2
}
```
- Untuk admin id ganti dengan id telegram kamu. Bisa di cari di bot @userinfobot

- DB name nya bebas mau di ganti apa aja asal .db tidak kamu hilangkan (optional)
- Max running untuk mengatur berapa jumlah maksimal user selain admin ngerun akun


#### .env

- Letakkan bot token disini

## License

[LICENSE]
(https://github.com/Fortoises/bussidbot-telegram/blob/main/LICENSE)

