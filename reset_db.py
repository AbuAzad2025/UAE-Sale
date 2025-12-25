import sys
from app import create_app
from extensions import db
from sqlalchemy import text

app = create_app()

def reset_database():
    print("WARNING: This will DROP ALL DATA in the database.")
    print("This is necessary to fix the schema synchronization issues.")
    
    with app.app_context():
        try:
            if db.engine.dialect.name == 'postgresql':
                print("PostgreSQL detected. Performing cascade schema drop...")
                with db.engine.connect() as conn:
                    # Execute raw SQL to drop schema cascade
                    # This handles circular dependencies by wiping the entire schema
                    conn.execute(text("DROP SCHEMA public CASCADE"))
                    conn.execute(text("CREATE SCHEMA public"))
                    # Ensure the user has access to the new schema
                    conn.execute(text("GRANT ALL ON SCHEMA public TO public")) 
                    conn.commit()
                print("Schema public dropped and recreated successfully.")
            else:
                print("Dropping all tables (Standard)...")
                db.drop_all()
                print("Dropping alembic_version...")
                try:
                    with db.engine.connect() as conn:
                        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
                        conn.commit()
                except Exception:
                    pass
                    
        except Exception as e:
            print(f"Error during schema reset: {e}")
            print("Trying fallback: Drop tables with CASCADE individually...")
            # Fallback for when schema drop fails (permissions)
            try:
                with db.engine.connect() as conn:
                    # Get all table names
                    result = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
                    tables = [row[0] for row in result]
                    for table in tables:
                        print(f"Dropping {table} CASCADE...")
                        conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
                    conn.commit()
            except Exception as e2:
                print(f"Fallback failed: {e2}")
                sys.exit(1)

        print("Database cleared.")
        print("Please run 'flask db upgrade' immediately after this.")

if __name__ == "__main__":
    reset_database()
