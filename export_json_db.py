import json
import os
import argparse
from datetime import datetime, date
from decimal import Decimal
from app import create_app
from extensions import db
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    return str(obj)

DEFAULT_EXCLUDE_TABLES = {
    "users",
    "roles",
    "permissions",
    "role_permissions",
    "login_history",
    "audit_logs",
}


def export_db_to_json(exclude_tables=None, output_path=None):
    print("Starting JSON export...")
    try:
        app = create_app()
    except Exception as e:
        print(f"Error creating app: {e}")
        return

    with app.app_context():
        data = {}
        
        try:
            # Get all tables
            tables = db.metadata.tables.keys()
            print(f"Found tables: {list(tables)}")

            exclude_set = {t.strip() for t in (exclude_tables or []) if t and t.strip()}
            
            for table_name in tables:
                if table_name in exclude_set:
                    print(f"Skipping excluded table: {table_name}")
                    continue

                print(f"Exporting {table_name}...")
                table_data = []
                
                try:
                    # Dynamically query the table
                    table = db.metadata.tables[table_name]
                    result = db.session.execute(table.select())
                    
                    # Get column names
                    columns = result.keys()
                    
                    for row in result:
                        row_dict = {}
                        for col in columns:
                            val = getattr(row, col)
                            row_dict[col] = val
                        table_data.append(row_dict)
                    
                    data[table_name] = table_data
                    print(f"Exported {len(table_data)} rows from {table_name}")
                except Exception as e:
                    print(f"Error exporting table {table_name}: {e}")
            
            # Create backups directory if not exists
            if not os.path.exists('instance/backups'):
                os.makedirs('instance/backups')
                
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = output_path or f'instance/backups/full_db_json_{timestamp}.json'
            
            print(f"Writing to file: {filename}")
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=json_serial)
                
            print(f"JSON Export completed successfully: {filename}")
            return filename
            
        except Exception as e:
            print(f"General error during export: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Export database tables to JSON.")
    parser.add_argument(
        "--exclude",
        default="",
        help="Comma-separated table names to exclude from export.",
    )
    parser.add_argument(
        "--exclude-defaults",
        action="store_true",
        help="Exclude default user-related tables (users, roles, permissions, ...).",
    )
    parser.add_argument(
        "--include-user-tables",
        action="store_true",
        help="Include user/security tables in export (users, roles, permissions, ...).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON file path. Default: instance/backups/full_db_json_<timestamp>.json",
    )
    args = parser.parse_args()

    exclude = {t.strip() for t in (args.exclude.split(",") if args.exclude else []) if t.strip()}

    if not args.include_user_tables:
        exclude |= DEFAULT_EXCLUDE_TABLES
    elif args.exclude_defaults:
        exclude |= DEFAULT_EXCLUDE_TABLES

    export_db_to_json(
        exclude_tables=sorted(exclude),
        output_path=(args.output.strip() or None),
    )
