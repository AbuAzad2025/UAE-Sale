import shutil
import os
import sys

def cleanup_migrations():
    print("!!! STARTING MIGRATION CLEANUP !!!")
    
    migrations_dir = 'migrations'
    
    if os.path.exists(migrations_dir):
        print(f"Removing '{migrations_dir}' directory...")
        try:
            shutil.rmtree(migrations_dir)
            print(">>> SUCCESS: Migrations folder removed.")
        except Exception as e:
            print(f"!!! ERROR Removing migrations folder: {e}")
            sys.exit(1)
    else:
        print("Migrations folder not found (already clean).")

    print("!!! CLEANUP COMPLETE. NOW RUN: !!!")
    print("1. flask db init")
    print("2. flask db migrate -m 'initial'")
    print("3. flask db upgrade")

if __name__ == "__main__":
    cleanup_migrations()
