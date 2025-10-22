from extensions import db
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


class DatabaseOptimizer:
    
    @staticmethod
    def vacuum_sqlite():
        if 'sqlite' in str(db.engine.url):
            try:
                db.session.execute(text('VACUUM'))
                db.session.execute(text('ANALYZE'))
                db.session.commit()
                logger.info("✅ SQLite database optimized (VACUUM + ANALYZE)")
                return {'success': True, 'message': 'Database optimized'}
            except Exception as e:
                logger.error(f"❌ Database optimization failed: {e}")
                return {'success': False, 'error': str(e)}
        return {'success': False, 'message': 'Not SQLite database'}
    
    @staticmethod
    def analyze_tables():
        try:
            if 'sqlite' in str(db.engine.url):
                db.session.execute(text('ANALYZE'))
                db.session.commit()
            elif 'postgresql' in str(db.engine.url):
                db.session.execute(text('ANALYZE'))
                db.session.commit()
            
            logger.info("✅ Database tables analyzed")
            return {'success': True}
        except Exception as e:
            logger.error(f"❌ Table analysis failed: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def get_table_sizes():
        try:
            if 'sqlite' in str(db.engine.url):
                result = db.session.execute(text("""
                    SELECT name, 
                           (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=m.name) as table_count
                    FROM sqlite_master m
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """))
                
                tables = []
                for row in result:
                    count_result = db.session.execute(text(f'SELECT COUNT(*) FROM {row[0]}'))
                    count = count_result.scalar()
                    tables.append({
                        'table_name': row[0],
                        'row_count': count
                    })
                
                return {'success': True, 'tables': tables}
            
            return {'success': False, 'message': 'Only SQLite supported'}
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def optimize_all():
        results = {}
        
        results['vacuum'] = DatabaseOptimizer.vacuum_sqlite()
        results['analyze'] = DatabaseOptimizer.analyze_tables()
        results['sizes'] = DatabaseOptimizer.get_table_sizes()
        
        return results

