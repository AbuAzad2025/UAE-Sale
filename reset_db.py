import sys
from app import create_app
from extensions import db
from sqlalchemy import text

app = create_app()

def reset_database():
    print("WARNING: This will DROP ALL DATA in the database.")
    print("This is necessary to fix the schema synchronization issues.")
    
    with app.app_context():
        print("Dropping all tables...")
        db.drop_all()
        
        print("Dropping alembic_version table...")
        try:
            with db.engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
                conn.commit()
        except Exception as e:
            print(f"Warning: {e}")
            
        print("Database cleared.")
        print("Please run 'flask db upgrade' immediately after this.")

if __name__ == "__main__":
    reset_database()
