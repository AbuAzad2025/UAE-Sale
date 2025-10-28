#!/usr/bin/env python
"""
إضافة الأعمدة المفقودة في جدول cheques
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from sqlalchemy import text, Integer, ForeignKey, Date

app = create_app()

print('\n' + '='*80)
print('🔧 إضافة الأعمدة المفقودة في جدول cheques')
print('='*80)

with app.app_context():
    inspector = db.inspect(db.engine)
    existing_columns = [col['name'] for col in inspector.get_columns('cheques')]
    
    print(f'\n📊 الأعمدة الموجودة حالياً: {len(existing_columns)}')
    
    # الأعمدة المطلوبة
    required_columns = {
        'purchase_id': 'INTEGER',
        'payment_id': 'INTEGER',
        'cleared_date': 'DATE'
    }
    
    added = 0
    skipped = 0
    
    for column_name, column_type in required_columns.items():
        if column_name not in existing_columns:
            try:
                print(f'\n  ➕ إضافة عمود: {column_name} ({column_type})')
                
                # إضافة العمود
                with db.engine.connect() as conn:
                    if column_name in ['purchase_id', 'payment_id']:
                        sql = f'ALTER TABLE cheques ADD COLUMN {column_name} {column_type} REFERENCES {"purchases" if "purchase" in column_name else "payments"}(id)'
                    else:
                        sql = f'ALTER TABLE cheques ADD COLUMN {column_name} {column_type}'
                    
                    conn.execute(text(sql))
                    conn.commit()
                
                print(f'    ✅ تمت إضافة {column_name}')
                added += 1
            except Exception as e:
                print(f'    ⚠️ خطأ في إضافة {column_name}: {str(e)}')
                if 'duplicate column' in str(e).lower():
                    print(f'    ℹ️ العمود موجود بالفعل')
                    skipped += 1
        else:
            print(f'  ℹ️ العمود {column_name} موجود بالفعل')
            skipped += 1
    
    print(f'\n{"="*80}')
    print(f'✅ اكتملت العملية:')
    print(f'  ➕ تمت إضافة: {added} أعمدة')
    print(f'  ℹ️ موجودة مسبقاً: {skipped} أعمدة')
    print(f'{"="*80}\n')

