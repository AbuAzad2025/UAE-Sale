import json
import os
import sys
import argparse
from datetime import datetime
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

USER_ID_COLUMN_NAMES = {
    "user_id",
    "seller_id",
    "manager_id",
    "created_by",
    "updated_by",
    "approved_by",
    "reversed_by",
    "archived_by",
}


def _detect_owner_user_id():
    from models.user import User

    owner_user = User.query.filter_by(is_owner=True).order_by(User.id.asc()).first()
    if owner_user:
        return owner_user.id

    any_user = User.query.order_by(User.id.asc()).first()
    if any_user:
        return any_user.id

    return None


def _column_targets_users(column):
    try:
        return any(getattr(fk.column.table, "name", None) == "users" for fk in column.foreign_keys)
    except Exception:
        return False


def _should_map_user_reference(col_name, column):
    if _column_targets_users(column):
        return True

    if col_name not in USER_ID_COLUMN_NAMES:
        return False

    try:
        return column.type.python_type is int
    except Exception:
        return False


def import_db_from_json(json_file_path, owner_user_id=None):
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
    
    if not isinstance(data, dict) or not data:
        print("Error: JSON file is empty or invalid (expected object with tables). Aborting.")
        return

    safe_tables = [
        "products",
        "product_categories",
        "customers",
        "suppliers",
        "sales",
        "purchases",
        "payments",
        "expenses",
        "warehouses",
    ]
    safe_counts = {t: len(data.get(t, []) or []) for t in safe_tables}
    total_rows = sum(len(rows) for rows in data.values() if isinstance(rows, list))
    print(f"JSON summary: tables={len(data)} total_rows={total_rows}")
    print("Key tables rows: " + ", ".join(f"{k}={v}" for k, v in safe_counts.items()))

    app = create_app()
    
    with app.app_context():
        try:
            if owner_user_id is None:
                owner_user_id = _detect_owner_user_id()
            if owner_user_id is None:
                raise RuntimeError("No users found in target DB to map user references.")

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

            if total_rows == 0 or all(v == 0 for v in safe_counts.values()):
                raise RuntimeError(
                    "Refusing to truncate/import because JSON looks empty for business tables. "
                    "Export from the real local database and try again."
                )
            
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
                            column = table.columns[col_name]
                            parsed_val = parse_value(val, column.type)

                            if _should_map_user_reference(col_name, column):
                                if parsed_val is None:
                                    if not column.nullable:
                                        parsed_val = owner_user_id
                                else:
                                    parsed_val = owner_user_id

                            clean_row[col_name] = parsed_val
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
    parser = argparse.ArgumentParser(description="Import database tables from JSON.")
    parser.add_argument("json_path", help="Path to JSON file exported from the database.")
    parser.add_argument(
        "--owner-user-id",
        type=int,
        default=0,
        help="Target production owner user id to map all user references to. Default: auto-detect.",
    )
    args = parser.parse_args()

    import_db_from_json(args.json_path, owner_user_id=(args.owner_user_id or None))
