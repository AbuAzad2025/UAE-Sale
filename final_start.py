import os
import sys
import time
import signal
import subprocess
import threading

def kill_app_processes():
    """Kill any existing app.py processes"""
    try:
        import psutil
        for p in psutil.process_iter(['pid', 'cmdline']):
            try:
                if p.info['cmdline'] and any('app.py' in str(cmd) for cmd in p.info['cmdline']):
                    print(f"Stopping process: {p.info['pid']}")
                    p.terminate()
                    p.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except ImportError:
        print("psutil not available")

# Start app
print("Starting app...")
proc = subprocess.Popen([sys.executable, 'app.py'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

# Start a thread to read and display output
def read_output(process):
    for line in iter(process.stdout.readline, ''):
        print(line, end='', flush=True)
    process.wait()

output_thread = threading.Thread(target=read_output, args=(proc,), daemon=True)
output_thread.start()

# Wait for server to start and test it
print("\nWaiting for server to start...")
for i in range(30):
    try:
        import urllib.request
        req = urllib.request.Request('http://127.0.0.1:8001/owner/dashboard')
        with urllib.request.urlopen(req, timeout=2) as response:  # nosec B310
            status_code = response.getcode()
            print(f"\nDashboard Status: {status_code}")

            # Try to read a bit of content to see if it's working
            try:
                body = response.read().decode('utf-8', errors='replace')
                if 'dashboard' in body.lower() or 'error' in body.lower():
                    print(f"Dashboard content preview (first 200 chars):")
                    print(body[:200].replace('\n', ' '))
                else:
                    print(f"Dashboard appears to be working with status {status_code}")
            except Exception:
                print("Could not read response body")

            print("\nServer is running successfully!")
            print("   Visit: http://127.0.0.1:8001/owner/dashboard")

            # Keep running
            try:
                output_thread.join()
            except Exception:
                break
            break
    except Exception as e:
        if i % 5 == 0:
            print(f"Attempt {i+1}/30: Waiting for server to start... (error: {type(e).__name__})")
        time.sleep(1)
else:
    print("\nFailed to start server after 30 attempts")
    # Print any output we received
    try:
        output_thread.join(timeout=2)
    except Exception:
        pass

print("\nServer stopped.")