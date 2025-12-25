import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from sqlalchemy import text, MetaData
from app import create_app
from extensions import db
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_value(value, column_type):
    """Parse value based on column type if needed"""
    if value is None:
        return None
    
    # Check if it looks like a date/datetime string
    if isinstance(value, str):
        # ISO format datetime
        if 'T' in value and '-' in value and ':' in value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        # Simple date
        elif '-' in value and value.count('-') == 2 and len(value) == 10:
            try:
                return datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                pass
                
    return value

def import_db_from_json(json_file_path):
    print(f"Starting JSON import from: {json_file_path}")
    
    if not os.path.exists(json_file_path):
        print(f"Error: File not found: {json_file_path}")
        return

    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON file: {e}")
        return

    app = create_app()
    
    with app.app_context():
        try:
            # Detect DB type
            dialect = db.engine.dialect.name
            print(f"Database dialect: {dialect}")
            
            connection = db.session.connection()
            
            # 1. Disable Constraints
            print("Disabling constraints...")
            if 'postgresql' in dialect:
                connection.execute(text("SET session_replication_role = 'replica';"))
            elif 'sqlite' in dialect:
                connection.execute(text("PRAGMA foreign_keys = OFF;"))
            
            # 2. Import Data
            meta = MetaData()
            meta.reflect(bind=db.engine)
            
            # We iterate over tables in the JSON
            # Ideally we should clear existing data first to avoid conflicts, 
            # or use the script on a fresh DB.
            # Here we assume a fresh DB or we truncate.
            
            # Let's truncate all tables first to be safe
            print("Truncating tables...")
            for table_name in data.keys():
                if table_name in meta.tables:
                    print(f"Cleaning {table_name}...")
                    try:
                        table = meta.tables[table_name]
                        connection.execute(table.delete())
                    except Exception as e:
                        print(f"Warning cleaning {table_name}: {e}")
            
            # Insert data
            for table_name, rows in data.items():
                if table_name not in meta.tables:
                    print(f"Skipping unknown table: {table_name}")
                    continue
                    
                print(f"Importing {len(rows)} rows into {table_name}...")
                table = meta.tables[table_name]
                
                if not rows:
                    continue
                    
                # Prepare data
                prepared_rows = []
                for row in rows:
                    clean_row = {}
                    for col_name, val in row.items():
                        if col_name in table.columns:
                            # Basic type inference/conversion could go here if needed
                            clean_row[col_name] = parse_value(val, table.columns[col_name].type)
                    prepared_rows.append(clean_row)
                
                # Bulk insert
                if prepared_rows:
                    connection.execute(table.insert(), prepared_rows)
            
            # 3. Reset Sequences (PostgreSQL only)
            if 'postgresql' in dialect:
                print("Resetting sequences...")
                for table_name in data.keys():
                    if table_name in meta.tables:
                        # Check if table has 'id' column with sequence
                        try:
                            # This is a generic way to reset sequence to max(id)
                            seq_reset_sql = f"""
                            SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE(MAX(id), 1)) FROM "{table_name}";
                            """
                            connection.execute(text(seq_reset_sql))
                        except Exception:
                            # Might fail if no id or no sequence, just ignore
                            pass

            # 4. Re-enable Constraints
            print("Re-enabling constraints...")
            if 'postgresql' in dialect:
                connection.execute(text("SET session_replication_role = 'origin';"))
            elif 'sqlite' in dialect:
                connection.execute(text("PRAGMA foreign_keys = ON;"))
            
            db.session.commit()
            print("Import completed successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"Error during import: {e}")
            import traceback
            traceback.print_exc()
        finally:
            pass

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python import_json_db.py <path_to_json_file>")
    else:
        import_db_from_json(sys.argv[1])
