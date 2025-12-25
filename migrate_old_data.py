import os
import sqlite3
import glob
from app import create_app
from extensions import db
from sqlalchemy import text

# Initialize Flask App
app = create_app()

OLD_DATA_DIR = os.path.join('instance', 'olddata')

def inspect_and_migrate():
    print(f"Looking for data in: {OLD_DATA_DIR}")
    if not os.path.exists(OLD_DATA_DIR):
        print(f"❌ Directory not found: {OLD_DATA_DIR}")
        print("Please upload your old .db or .sqlite files to this folder.")
        return

    db_files = glob.glob(os.path.join(OLD_DATA_DIR, '*.db')) + glob.glob(os.path.join(OLD_DATA_DIR, '*.sqlite'))
    
    if not db_files:
        print("❌ No database files found.")
        return

    print(f"Found {len(db_files)} database files.")

    for db_file in db_files:
        print(f"\n--- Processing {os.path.basename(db_file)} ---")
        try:
            conn = sqlite3.connect(db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [t[0] for t in cursor.fetchall()]
            print(f"Tables found: {tables}")

            # Example Migration Logic (Customize based on actual table names)
            # This is a generic framework - we need to know the table names to map them.
            
            # if 'products' in tables:
            #     migrate_products(cursor)
            
            conn.close()
        except Exception as e:
            print(f"❌ Error processing file: {e}")

def migrate_products(cursor):
    print("Migrating Products...")
    # Implement mapping logic here
    pass

if __name__ == "__main__":
    with app.app_context():
        inspect_and_migrate()
