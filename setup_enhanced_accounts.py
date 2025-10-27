#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
إنشاء الحسابات المحاسبية المتقدمة
Setup Enhanced GL Accounts
"""

from app import create_app
from services.gl_service import GLService
from extensions import db

app = create_app()

with app.app_context():
    print("=" * 70)
    print("🔧 إنشاء الحسابات المحاسبية المتقدمة")
    print("=" * 70)
    
    try:
        GLService.ensure_core_accounts()
        
        from models import GLAccount
        
        # عرض الإحصائيات
        total = GLAccount.query.count()
        headers = GLAccount.query.filter_by(is_header=True).count()
        accounts_by_type = {
            'asset': GLAccount.query.filter_by(type='asset').count(),
            'liability': GLAccount.query.filter_by(type='liability').count(),
            'equity': GLAccount.query.filter_by(type='equity').count(),
            'revenue': GLAccount.query.filter_by(type='revenue').count(),
            'expense': GLAccount.query.filter_by(type='expense').count(),
        }
        
        print(f"\n✅ تم إنشاء الحسابات بنجاح!")
        print(f"\n📊 الإحصائيات:")
        print(f"   📝 إجمالي الحسابات: {total}")
        print(f"   📂 حسابات رئيسية: {headers}")
        print(f"   💰 الأصول: {accounts_by_type['asset']}")
        print(f"   💳 الخصوم: {accounts_by_type['liability']}")
        print(f"   🏦 حقوق الملكية: {accounts_by_type['equity']}")
        print(f"   📈 الإيرادات: {accounts_by_type['revenue']}")
        print(f"   📉 المصروفات: {accounts_by_type['expense']}")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ خطأ: {e}")
        import traceback
        traceback.print_exc()

