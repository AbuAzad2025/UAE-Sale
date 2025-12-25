import os
import sys
import subprocess
import secrets
import shutil
from pathlib import Path

# ANSI colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'

def print_step(msg):
    print(f"\n{GREEN}>>> {msg}{RESET}")

def print_error(msg):
    print(f"{RED}!!! {msg}{RESET}")

def run_command(command, ignore_errors=False):
    print(f"Executing: {command}")
    result = subprocess.run(command, shell=True)
    if result.returncode != 0:
        if not ignore_errors:
            print_error(f"Command failed: {command}")
            sys.exit(1)
        else:
            print(f"{YELLOW}Command failed but continuing...{RESET}")

def check_env_vars():
    print_step("Checking environment variables (.env)...")
    env_file = ".env"
    
    # Generate secure keys
    enc_key = secrets.token_urlsafe(32)
    sec_key = secrets.token_hex(32)
    
    required_vars = {
        "CARD_ENCRYPTION_KEY": enc_key,
        "SECRET_KEY": sec_key,
        "FLASK_APP": "app.py",
        "FLASK_ENV": "production",
        # We try to guess the base URL or leave it for user to verify
        "BASE_URL": "https://NASERALLAH.pythonanywhere.com"
    }
    
    existing_vars = {}
    if os.path.exists(env_file):
        with open(env_file, "r", encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and "=" in line:
                    key, val = line.split("=", 1)
                    existing_vars[key] = val
    
    # Append missing vars
    with open(env_file, "a", encoding='utf-8') as f:
        if os.path.getsize(env_file) > 0 and not open(env_file, 'r', encoding='utf-8').read().endswith('\n'):
            f.write("\n")
            
        for key, default_val in required_vars.items():
            if key not in existing_vars:
                print(f"Adding missing variable: {key}")
                f.write(f"{key}={default_val}\n")
            else:
                print(f"Variable exists: {key}")
                
    # Check DATABASE_URL
    if "DATABASE_URL" not in existing_vars:
        print_error("DATABASE_URL is missing from .env!")
        print("Please add it manually or via PythonAnywhere dashboard.")
        # We don't exit, maybe it's in system env
    else:
        print("DATABASE_URL found.")

def reset_database_logic():
    print_step("Resetting Database (Wiping Schema)...")
    
    # Try to import reset_db logic
    try:
        if os.path.exists("reset_db.py"):
            subprocess.run([sys.executable, "reset_db.py"], check=True)
        else:
            print_error("reset_db.py not found!")
    except Exception as e:
        print_error(f"Failed to reset database: {e}")
        sys.exit(1)

def handle_migrations():
    print_step("Re-initializing Migrations...")
    
    if os.path.exists("migrations"):
        print("Removing 'migrations' directory...")
        shutil.rmtree("migrations")
    
    run_command("flask db init")
    run_command("flask db migrate -m 'initial_production_setup'")
    run_command("flask db upgrade")

def check_old_data():
    print_step("Checking for old data to migrate...")
    old_data_dir = os.path.join("instance", "olddata")
    
    if os.path.exists(old_data_dir) and os.listdir(old_data_dir):
        print(f"Found files in {old_data_dir}. Attempting migration...")
        if os.path.exists("migrate_old_data.py"):
            run_command(f"{sys.executable} migrate_old_data.py", ignore_errors=True)
        else:
            print(f"{YELLOW}migrate_old_data.py not found. Skipping migration.{RESET}")
    else:
        print("No old data found in instance/olddata. Skipping.")

def main():
    print(f"{GREEN}=========================================={RESET}")
    print(f"{GREEN}   GARAGE MANAGER - PRODUCTION SETUP      {RESET}")
    print(f"{GREEN}=========================================={RESET}")
    
    # 1. Environment
    check_env_vars()
    
    # 2. Database Reset
    reset_database_logic()
    
    # 3. Migrations
    handle_migrations()
    
    # 4. Old Data (Optional)
    check_old_data()
    
    print(f"\n{GREEN}=========================================={RESET}")
    print(f"{GREEN}   SETUP COMPLETE SUCCESSFULLY!           {RESET}")
    print(f"{GREEN}=========================================={RESET}")
    print("Next Steps:")
    print("1. Go to PythonAnywhere 'Web' tab.")
    print("2. Click 'Reload <your-domain>'.")
    print("3. Open your website.")

if __name__ == "__main__":
    main()
