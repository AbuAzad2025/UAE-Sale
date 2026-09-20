#!/usr/bin/env python3

import os
import sys
import time
import subprocess

# Set environment variables
os.environ['DEBUG'] = 'true'
os.environ['APP_ENV'] = 'development'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['CARD_ENCRYPTION_KEY'] = 'test-card-enc-key'
os.environ['OWNER_PASSWORD'] = 'test-owner-password'
os.environ['PORT'] = '8001'
os.environ['HOST'] = '127.0.0.1'
os.environ['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:123@localhost:5432/uae_sale_8001'

# Kill any existing python app.py processes
try:
    # Find and kill python processes running app.py
    import psutil
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.info['cmdline'] and any('app.py' in str(cmd) for cmd in proc.info['cmdline']):
                print(f"Stopping process: {proc.info['pid']}")
                proc.terminate()
                proc.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
except ImportError:
    print("psutil not available, trying with taskkill")

# Start app
print("Starting app...")
proc = subprocess.Popen([sys.executable, 'app.py'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

# Wait for server to start
print("Waiting for server to start...")
time.sleep(10)

# Test the endpoint
try:
    import urllib.request
    req = urllib.request.Request('http://127.0.0.1:8001/owner/dashboard')
    with urllib.request.urlopen(req, timeout=10) as response:
        status_code = response.getcode()
        print(f"Dashboard Status: {status_code}")
        if status_code == 200:
            print("✅ Server working! Dashboard accessible.")
        else:
            print(f"⚠️ Dashboard returned status: {status_code}")
            
            # Try to read any output from the server
            if proc.poll() is not None:
                output = proc.stdout.read()
                print(f"Server output: {output[-500:]}")
except Exception as e:
    print(f"❌ Error: {e}")
    print("Server may not be running properly")
    
    # Try to read server output
    try:
        if proc.poll() is not None:
            output = proc.stdout.read()
            print(f"Server output: {output[-1000:]}")
    except:
        pass