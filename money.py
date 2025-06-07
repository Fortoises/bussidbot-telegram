import requests
import json
import time
import threading
import queue
import random
import logging

# Setup logging ke file debug.log
logging.basicConfig(
    filename='debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'
)

# Daftar rute
routes = [
    ["PBR", "JMB", "PLB", "LPG", "P_Bakauheni", "P_Merak", "JKT", "CBN", "SMG", "SBY", "BKL"],
    ["PBR", "JMB", "PLB", "LPG", "P_Bakauheni", "P_Merak", "JKT", "CBN", "SMG", "SBY"],
    ["PBR", "JMB", "PLB", "LPG", "P_Bakauheni", "P_Merak", "JKT", "CBN", "SMG", "SBY", "MLG"]
]

# Data rute awal (fallback)
record = [
    {'Key': {'sourceCity': 'MLG', 'destinationCity': 'SBY', 'routePassed': ['SBY', 'MLG'], 'activityRewards': None}, 'Value': 30},
    {'Key': {'sourceCity': 'SBY', 'destinationCity': 'SMG', 'routePassed': ['SMG', 'SBY'], 'activityRewards': None}, 'Value': 60},
    {'Key': {'sourceCity': 'MLG', 'destinationCity': 'SMG', 'routePassed': ['SMG', 'MLG'], 'activityRewards': None}, 'Value': 12},
    {'Key': {'sourceCity': 'SMG', 'destinationCity': 'CBN', 'routePassed': ['CBN', 'SMG'], 'activityRewards': None}, 'Value': 50},
    {'Key': {'sourceCity': 'SBY', 'destinationCity': 'CBN', 'routePassed': ['CBN', 'SBY'], 'activityRewards': None}, 'Value': 10},
    {'Key': {'sourceCity': 'MLG', 'destinationCity': 'CBN', 'routePassed': ['CBN', 'MLG'], 'activityRewards': None}, 'Value': 5},
    {'Key': {'sourceCity': 'CBN', 'destinationCity': 'JKT', 'routePassed': ['JKT', 'CBN'], 'activityRewards': None}, 'Value': 45},
    {'Key': {'sourceCity': 'SMG', 'destinationCity': 'JKT', 'routePassed': ['JKT', 'SMG'], 'activityRewards': None}, 'Value': 9},
    {'Key': {'sourceCity': 'SBY', 'destinationCity': 'JKT', 'routePassed': ['JKT', 'SBY'], 'activityRewards': None}, 'Value': 5},
    {'Key': {'sourceCity': 'MLG', 'destinationCity': 'JKT', 'amount': 0}, 'Value': 3},
    {'Key': {'sourceCity': 'JKT', 'destinationCity': 'P_Merak', 'amount': 45}, 'Value': 90}
]

# Manajemen worker per akun
workers = {}  # {account_name: {"thread": Thread, "event": Event, "session": Session}}
lock = threading.Lock()

def create_mission(session, headers):
    selected_cities = random.choice(routes)
    game_data = json.dumps({
        "FunctionName": "PlayCareer",
        "FunctionParameter": {"cities": selected_cities},
        "RevisionSelection": "Live",
        "SpecificRevision": None,
        "GeneratePlayStreamEvent": False
    })
    
    retries = 3
    for attempt in range(retries):
        try:
            response = session.post('https://4ae9.playfabapi.com/Client/ExecuteCloudScript', headers=headers, data=game_data)
            response.raise_for_status()
            parser = response.json()
            
            logging.debug(f"[create_mission] Cities: {selected_cities}")
            logging.debug(f"[create_mission] Response: {json.dumps(parser, indent=2)}")
            
            if parser.get('code') == 401:
                logging.error("Unauthorized (401). Periksa token auth.")
                return None
            elif parser.get('code') == 429:
                retry_after = parser.get('data', {}).get('Error', {}).get('retryAfterSeconds', 2)
                logging.warning(f"Rate limit exceeded (429). Menunggu {retry_after} detik...")
                time.sleep(retry_after + random.uniform(0.1, 0.5))
                continue
            elif parser.get('code') == 200:
                data = parser.get('data', {})
                if "apiError" in data:
                    logging.error(f"API error detected - {data['apiError']}")
                    return None
                if 'FunctionResult' not in data or 'careerSession' not in data['FunctionResult']:
                    logging.error(f"'FunctionResult' or 'careerSession' missing - {data}")
                    return None
                logging.info("Successfully created mission")
                return data['FunctionResult']['careerSession']
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed: {e}. Retrying ({attempt + 1}/{retries})...")
            time.sleep(0.5 + random.uniform(0.1, 0.3))
    logging.error("Gagal setelah 3 percobaan di create_mission.")
    return None

def reset_user_fuel(session, headers):
    data = json.dumps({
        "FunctionName": "ResetUserFuel",
        "FunctionParameter": None,
        "RevisionSelection": "Live",
        "SpecificRevision": None,
        "GeneratePlayStreamEvent": False
    })
    
    retries = 3
    for attempt in range(retries):
        try:
            response = session.post('https://4ae9.playfabapi.com/Client/ExecuteCloudScript', headers=headers, data=data)
            response.raise_for_status()
            parser = response.json()
            
            logging.debug(f"[reset_user_fuel] Response: {json.dumps(parser, indent=4)}")
            
            if parser.get('code') == 401:
                logging.error("Unauthorized (401) in reset_user_fuel.")
                return False
            elif parser.get('code') == 429:
                retry_after = parser.get('data', {}).get('Error', {}).get('retryAfterSeconds', 2)
                logging.warning(f"Rate limit exceeded (429) in reset_user_fuel. Menunggu {retry_after} detik...")
                time.sleep(retry_after + random.uniform(0.1, 0.5))
                continue
            elif parser.get('code') == 200:
                backend_data = parser.get('data', {})
                if "apiError" in backend_data:
                    logging.error(f"API error detected in reset_user_fuel - {backend_data['apiError']}")
                    return False
                logging.info(f"Successfully reset fuel: {backend_data.get('FunctionResult', 'No result')}")
                return True
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed in reset_user_fuel: {e}. Retrying ({attempt + 1}/{retries})...")
            time.sleep(0.5 + random.uniform(0.1, 0.3))
    logging.error("Gagal setelah 3 percobaan di reset_user_fuel.")
    return False

def skip_mission(session, headers, token, passenger_data):
    failed_routes = set()
    dynamic_record = [
        {
            'Key': {
                'sourceCity': p['source'],
                'destinationCity': p['destination'],
                'routePassed': [p['destination'], p['source']],
                'activityRewards': None
            },
            'Value': p['amount']
        } for p in sorted(passenger_data, key=lambda x: x['amount'], reverse=True)[:3]
        if p['amount'] > 0 and (p['source'], p['destination']) not in failed_routes
    ]
    
    if not dynamic_record:
        dynamic_record = [random.choice(record)]
        logging.warning(f"No valid routes in passenger_data, using fallback: {dynamic_record}")
    
    data = json.dumps({
        "FunctionName": "FarePayment",
        "FunctionParameter": {
            "records": dynamic_record,
            "bonus": True,
            "careerToken": token,
            "activityRewardToken": "{\"rewards\":[]}"
        },
        "RevisionSelection": "Live",
        "SpecificRevision": None,
        "GeneratePlayStreamEvent": False
    })
    
    retries = 3
    for attempt in range(retries):
        try:
            response = session.post('https://4ae9.playfabapi.com/Client/ExecuteCloudScript', headers=headers, data=data)
            response.raise_for_status()
            parser = response.json()
            
            logging.debug(f"[skip_mission] Response for token {token}: {json.dumps(parser, indent=4)}")
            
            if parser.get('code') == 401:
                logging.error(f"[{token}] Unauthorized (401).")
                return False
            elif parser.get('code') == 429:
                retry_after = parser.get('data', {}).get('Error', {}).get('retryAfterSeconds', 2)
                logging.warning(f"[{token}] Rate limit exceeded (429). Menunggu {retry_after} detik...")
                time.sleep(retry_after + random.uniform(0.1, 0.5))
                continue
            elif parser.get('code') == 200:
                backend_data = parser.get('data', {})
                if "apiError" in backend_data:
                    logging.error(f"[{token}] API error detected - {backend_data['apiError']}")
                    if "Terminal has been visited" in str(backend_data['apiError']):
                        for route in dynamic_record:
                            failed_routes.add((route['Key']['sourceCity'], route['Key']['destinationCity']))
                        logging.warning(f"Added routes to failed_routes: {failed_routes}")
                    return False
                logs = backend_data.get('Logs', [])
                msg = logs[-1]['Message'] if logs else "No message"
                with lock:
                    logging.info(f"[{token}] {msg}")
                return True
        except requests.exceptions.RequestException as e:
            logging.error(f"[{token}] Request failed: {e}. Retrying ({attempt + 1}/{retries})...")
            time.sleep(0.5 + random.uniform(0.1, 0.3))
    logging.error(f"[{token}] Gagal setelah 3 percobaan di skip_mission.")
    return False

def pass_mission_worker(account_name, auth, stop_event):
    headers = {
        'User-Agent': 'UnityEngine-Unity; Version: 2018.4.26f1',
        'X-ReportErrorAsSuccess': 'true',
        'X-PlayFabSDK': 'UnitySDK-2.20.170411',
        'X-Authorization': auth,
        'Content-Type': 'application/json'
    }
    session = requests.Session()
    error_count = 0
    max_errors = 5
    
    while not stop_event.is_set():
        try:
            career = create_mission(session, headers)
            if career and 'token' in career and 'passenger' in career:
                token = career['token']
                passenger_data = career['passenger']
                if skip_mission(session, headers, token, passenger_data):
                    reset_user_fuel(session, headers)
                    error_count = 0
                else:
                    error_count += 1
            else:
                logging.warning(f"[{account_name}] Tidak ada careerSession, token, atau passenger.")
                error_count += 1
            if error_count >= max_errors:
                logging.warning(f"[{account_name}] Terlalu banyak error ({error_count}). Menunggu 5 detik...")
                time.sleep(5 + random.uniform(0.5, 1.0))
                error_count = 0
            else:
                time.sleep(1 + random.uniform(0.3, 0.7))
        except Exception as e:
            logging.error(f"[{account_name}] Worker error: {str(e)}")
            error_count += 1
            time.sleep(2 + random.uniform(0.5, 1.0))
    
    session.close()
    logging.info(f"[{account_name}] Worker stopped")

def start_money_worker(account_name, auth):
    with lock:
        if account_name in workers:
            return False
        stop_event = threading.Event()
        thread = threading.Thread(target=pass_mission_worker, args=(account_name, auth, stop_event))
        thread.daemon = True
        workers[account_name] = {"thread": thread, "event": stop_event, "session": requests.Session()}
        thread.start()
        logging.info(f"Started money worker for {account_name}")
        return True

def stop_money_worker(account_name):
    with lock:
        if account_name not in workers:
            return False
        workers[account_name]["event"].set()
        workers[account_name]["thread"].join(timeout=5)
        workers[account_name]["session"].close()
        del workers[account_name]
        logging.info(f"Stopped money worker for {account_name}")
        return True

def is_worker_running(account_name):
    with lock:
        return account_name in workers and workers[account_name]["thread"].is_alive()

def get_running_workers():
    with lock:
        return [name for name, worker in workers.items() if worker["thread"].is_alive()]