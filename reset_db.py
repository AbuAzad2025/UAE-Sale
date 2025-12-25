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
                print(">>> PostgreSQL detected. Executing FORCE CASCADE DROP...")
                with db.engine.connect() as conn:
                    # 1. Kill all other connections to the database to ensure we can drop everything
                    try:
                        conn.execute(text("""
                            SELECT pg_terminate_backend(pid) 
                            FROM pg_stat_activity 
                            WHERE datname = current_database() 
                            AND pid <> pg_backend_pid()
                        """))
                        print(">>> Terminated other connections.")
                    except Exception as e:
                        print(f"Warning (Connection Kill): {e}")

                    # 2. Force drop schema
                    conn.execute(text("DROP SCHEMA public CASCADE"))
                    conn.execute(text("CREATE SCHEMA public"))
                    conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
                    conn.execute(text("GRANT ALL ON SCHEMA public TO super")) 
                    
                    # 3. Explicitly drop alembic_version table just in case it survived in another schema
                    conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
                    
                    conn.commit()
                print(">>> SUCCESS: Schema public recreated.")
            else:
                # SQLite
                db.drop_all()
                try:
                    with db.engine.connect() as conn:
                        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
                        conn.commit()
                except Exception:
                    pass
                print(">>> SUCCESS: Tables dropped.")
                
        except Exception as e:
            print(f"!!! ERROR: {e}")
            sys.exit(1)

    print("!!! DATABASE RESET COMPLETE. NOW RUN 'flask db upgrade' !!!")

if __name__ == "__main__":
    reset_database()
