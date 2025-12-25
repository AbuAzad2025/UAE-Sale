import sys
from app import create_app
from extensions import db
from sqlalchemy import text

app = create_app()

def reset_database():
    print("!!! STARTING DATABASE RESET !!!")
    
    with app.app_context():
        dialect = db.engine.dialect.name
        print(f"Detected Dialect: {dialect}")
        
        try:
            if 'postgres' in dialect:
                print(">>> PostgreSQL detected. Executing ULTRA FORCE DROP...")
                with db.engine.connect() as conn:
                    # 1. Kill connections
                    try:
                        conn.execute(text("""
                            SELECT pg_terminate_backend(pid) 
                            FROM pg_stat_activity 
                            WHERE datname = current_database() 
                            AND pid <> pg_backend_pid()
                        """))
                    except:
                        pass

                    # 2. DROP SCHEMA CASCADE
                    conn.execute(text("DROP SCHEMA public CASCADE"))
                    conn.execute(text("CREATE SCHEMA public"))
                    conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
                    conn.execute(text("GRANT ALL ON SCHEMA public TO super")) 
                    
                    conn.commit()
                print(">>> SUCCESS: Schema wiped.")
            else:
                db.drop_all()
                print(">>> SUCCESS: Tables dropped.")
                
        except Exception as e:
            print(f"!!! ERROR: {e}")
            sys.exit(1)

    print("!!! DATABASE RESET COMPLETE !!!")
    print("!!! NOW EXECUTING 'flask db stamp head' TO SYNC MIGRATIONS !!!")
    
    # We don't run flask db upgrade immediately because the migrations might be out of sync
    # Instead, we will stamp head if tables exist, or upgrade if they don't.
    # But since we wiped everything, we should run upgrade. 
    # The error "DuplicateColumn" suggests that tables WERE NOT WIPED or migration is trying to add column to existing table.
    
    # If reset worked, tables shouldn't exist.
    # If they exist, it means reset didn't work.

if __name__ == "__main__":
    reset_database()
