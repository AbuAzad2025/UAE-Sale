"""تنفيذ مباشر من Plan — بدون Groq، حتى الاكتمال.

الهدف (Phase 2b):
- فصل منطق التنفيذ عن التفسير (Groq)
- كل إجراء يمر: صلاحية → tenant → اكتمال → تأكيد (للمدمّر) → Service رسمي → تدقيق
- القراءات فقط تستخدم الاستعلامات المقيدة بالتينة مباشرة.

المسار:
  services/ai_planner.plan() → services/ai_executor.execute_plan()
"""
from __future__ import annotations


_MISSING_AR = {
    'name': 'الاسم',
    'customer_name': 'اسم العميل',
    'product_name': 'اسم المنتج',
    'supplier_name': 'اسم المورد',
    'amount': 'المبلغ',
    'new_balance': 'الرصيد الجديد',
    'description': 'الوصف',
    'cheque_number': 'رقم الشيك',
    'query': 'كلمة البحث',
}


def _permission_denied(user, permission_code: str) -> str | None:
    if user is None or not getattr(user, 'is_authenticated', False):
        return '⛔ يجب تسجيل الدخول أولاً لتنفيذ هذا الإجراء عبر المساعد الذكي.'
    if getattr(user, 'is_owner', False):
        return None
    is_super = getattr(user, 'is_super_admin', None)
    if callable(is_super):
        try:
            if is_super():
                return None
        except Exception:
            pass
    has_perm = getattr(user, 'has_permission', None)
    if callable(has_perm) and has_perm(permission_code):
        return None
    return f'⛔ ليس لديك صلاحية لتنفيذ هذا الإجراء عبر المساعد الذكي. هذه العملية تتطلب: {permission_code}.'


def _tenant_denied(user, is_write: bool) -> str | None:
    if not is_write:
        return None
    if user is None:
        return '⛔ يجب تسجيل الدخول أولاً.'
    if getattr(user, 'is_owner', False):
        return None
    is_super = getattr(user, 'is_super_admin', None)
    if callable(is_super):
        try:
            if is_super():
                return None
        except Exception:
            pass
    if not getattr(user, 'tenant_id', None):
        return ('⛔ حسابك غير مرتبط بشركة (tenant). لا يمكن تنفيذ عمليات عبر المساعد الذكي. '
                'تواصل مع مالك المنصة لربط حسابك بشركة أولاً.')
    return None


def _missing_message(tool: str, missing: list[str]) -> str:
    labels = [_MISSING_AR.get(m, m) for m in missing]
    joined = '، '.join(labels)
    return f'👋 فهمتك — لكن نحتاج قبل التنفيذ: **{joined}**. أكرم بالكتابة بصيغة: «{tool}: الاسم، ...».'


def _confirm_message(tool: str, params: dict) -> str:
    bits = '، '.join(f'{k}: {v}' for k, v in params.items())
    return (f'⚠️ **تأكيد مطلوب** — هذا تعديل رصيد (عملية مدمّرة).\n'
            f'التفاصيل: {bits}\n'
            f'اكتب **نعم** للتأكيد أو **لا** للإلغاء.')


def _find_customer(user, name: str):
    from models.customer import Customer
    if not name:
        return None
    q = Customer.query.filter_by(is_active=True)
    # عزل دفاعي صريح فوق ORM
    if user is not None and not getattr(user, 'is_owner', False):
        tid = getattr(user, 'tenant_id', None)
        if tid:
            q = q.filter(Customer.tenant_id == tid)
    # أولاً مطابقة تامة ثم جزئية
    exact = q.filter(Customer.name == name).first()
    if exact:
        return exact
    return q.filter(Customer.name.like(f'%{name}%')).first()


def _find_product(user, name: str):
    from models.product import Product
    if not name:
        return None
    q = Product.query.filter_by(is_active=True)
    if user is not None and not getattr(user, 'is_owner', False):
        tid = getattr(user, 'tenant_id', None)
        if tid:
            q = q.filter(Product.tenant_id == tid)
    exact = q.filter(Product.name == name).first()
    if exact:
        return exact
    return q.filter(Product.name.like(f'%{name}%')).first()


def _find_supplier(user, name: str):
    from models.supplier import Supplier
    if not name:
        return None
    q = Supplier.query.filter_by(is_active=True)
    if user is not None and not getattr(user, 'is_owner', False):
        tid = getattr(user, 'tenant_id', None)
        if tid:
            q = q.filter(Supplier.tenant_id == tid)
    exact = q.filter(Supplier.name == name).first()
    if exact:
        return exact
    return q.filter(Supplier.name.like(f'%{name}%')).first()


def _dec(value, default=0):
    from decimal import Decimal
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(str(default))


def execute_plan(plan, user, confirmed: bool = False) -> dict:
    """تنفيذ Plan كاملة. تُرجع {executed, response, needs_clarification}."""
    from services.ai_tools import TOOLS_BY_NAME

    if plan is None or not getattr(plan, 'tool', None):
        return {'executed': False, 'response': '', 'needs_clarification': False}

    tool = plan.tool
    tool_def = TOOLS_BY_NAME.get(tool)
    if tool_def is None:
        return {'executed': False, 'response': f'⚠️ أداة غير معروفة: {tool}', 'needs_clarification': False}

    # 1) الصلاحية
    denied = _permission_denied(user, tool_def.permission)
    if denied:
        return {'executed': False, 'response': denied, 'needs_clarification': False}

    # 2) Tenant (الكتابة فقط)
    is_write = tool not in ('get_customer_balance', 'inventory_status', 'sales_summary', 'search_customers')
    denied_t = _tenant_denied(user, is_write)
    if denied_t:
        return {'executed': False, 'response': denied_t, 'needs_clarification': False}

    # 3) اكتمال
    if plan.missing_fields:
        return {'executed': False, 'response': _missing_message(tool, plan.missing_fields),
                'needs_clarification': True}

    # 4) تأكيد للمدمّر
    if tool_def.destructive and not confirmed:
        return {'executed': False, 'response': _confirm_message(tool, plan.params),
                'needs_clarification': True}

    # 5) التنفيذ
    try:
        from services import ai_commands as cmd

        p = plan.params or {}

        if tool == 'search_customers':
            from models.customer import Customer
            q = Customer.query.filter_by(is_active=True)
            if user is not None and not getattr(user, 'is_owner', False) and getattr(user, 'tenant_id', None):
                q = q.filter(Customer.tenant_id == user.tenant_id)
            rows = q.filter(Customer.name.like(f"%{p.get('query', '')}%")).limit(10).all()
            if not rows:
                return {'executed': True, 'response': '🔍 لا يوجد عملاء مطابقون.', 'needs_clarification': False}
            lines = [f'- {c.name} (الرصيد: {c.balance})' for c in rows]
            return {'executed': True, 'response': '🔍 **عملاء مطابقون:**\n' + '\n'.join(lines), 'needs_clarification': False}

        if tool == 'get_customer_balance':
            c = _find_customer(user, p.get('customer_name'))
            if not c:
                return {'executed': True, 'response': f'🔍 لم أجد العميل «{p.get("customer_name")}».', 'needs_clarification': False}
            return {'executed': True,
                    'response': f'💰 رصيد العميل **{c.name}**: {c.balance} درهم', 'needs_clarification': False}

        if tool == 'inventory_status':
            from models.product import Product
            q = Product.query.filter_by(is_active=True)
            if user is not None and not getattr(user, 'is_owner', False) and getattr(user, 'tenant_id', None):
                q = q.filter(Product.tenant_id == user.tenant_id)
            total = q.count()
            low = q.filter(Product.current_stock <= Product.min_stock_alert).count()
            return {'executed': True,
                    'response': f'📦 **حالة المخزون:** {total} منتج نشط، {low} بمستوى منخفض.', 'needs_clarification': False}

        if tool == 'sales_summary':
            from models.sale import Sale
            from datetime import datetime, timedelta
            from sqlalchemy import func
            from extensions import db
            days = int(p.get('days', 30) or 30)
            since = datetime.now() - timedelta(days=days)
            q = Sale.query.filter(Sale.sale_date >= since)
            if user is not None and not getattr(user, 'is_owner', False) and getattr(user, 'tenant_id', None):
                q = q.filter(Sale.tenant_id == user.tenant_id)
            n = q.count()
            total = db.session.query(func.sum(Sale.total_amount)).filter(Sale.sale_date >= since).scalar() or 0
            return {'executed': True,
                    'response': f'📊 **مبيعات {days} يوم:** {n} فاتورة ({total} درهم).', 'needs_clarification': False}

        if tool == 'create_customer':
            c = cmd.create_customer(name=p.get('name'), phone=p.get('phone'), address=p.get('address'))
            return {'executed': True, 'response': f'✅ تم إنشاء العميل **{c.name}**.', 'needs_clarification': False}

        if tool == 'create_product':
            price = _dec(p.get('price', p.get('regular_price', 0)))
            cost = _dec(p.get('cost_price', 0))
            qty = _dec(p.get('quantity', 0))
            prod = cmd.create_product(name=p.get('name'), regular_price=price,
                                      current_stock=qty, cost_price=cost)
            return {'executed': True, 'response': f'✅ تم إنشاء المنتج **{prod.name}**.', 'needs_clarification': False}

        if tool == 'create_supplier':
            s = cmd.create_supplier(name=p.get('name'), phone=p.get('phone'), address=p.get('address'))
            return {'executed': True, 'response': f'✅ تم إنشاء المورد **{s.name}**.', 'needs_clarification': False}

        if tool == 'create_sale':
            cust = _find_customer(user, p.get('customer_name'))
            if not cust:
                return {'executed': False, 'response': f'🔍 العميل «{p.get("customer_name")}» غير موجود. أنشئه أولاً.', 'needs_clarification': True}
            prod = _find_product(user, p.get('product_name'))
            if not prod:
                return {'executed': False, 'response': f'🔍 المنتج «{p.get("product_name")}» غير موجود. أنشئه أولاً.', 'needs_clarification': True}
            qty = _dec(p.get('quantity', 1))
            sale = cmd.create_sale(customer_id=cust.id, product_id=prod.id, quantity=qty,
                                   seller_id=getattr(user, 'id', None))
            return {'executed': True,
                    'response': f'✅ تم إنشاء فاتورة بيع #{getattr(sale, "id", "?")} لـ **{cust.name}** ({prod.name} × {qty}).',
                    'needs_clarification': False}

        if tool == 'record_payment':
            cust = _find_customer(user, p.get('customer_name'))
            if not cust:
                return {'executed': False, 'response': f'🔍 العميل «{p.get("customer_name")}» غير موجود.', 'needs_clarification': True}
            amount = _dec(p.get('amount', 0))
            if amount <= 0:
                return {'executed': False, 'response': '⚠️ المبلغ يجب أن يكون أكبر من صفر.', 'needs_clarification': True}
            direction = p.get('direction', 'incoming')  # receive=استلام، give=إعطاء
            if plan.intent == 'give' or direction == 'outgoing':
                from services.payment_service import PaymentService
                PaymentService.create_refund(customer=cust, amount=amount,
                                             reason='استرداد عبر المساعد الذكي',
                                             payment_method=p.get('method', 'cash'),
                                             user_id=getattr(user, 'id', None))
                return {'executed': True,
                        'response': f'✅ تم تسجيل دفع **{amount} درهم** للعميل {cust.name} (استرداد).',
                        'needs_clarification': False}
            from services.payment_service import PaymentService
            from services.currency_service import CurrencyService
            try:
                currency = CurrencyService.get_base_currency()
            except Exception:
                currency = 'ILS'
            PaymentService.create_receipt({
                'customer_id': cust.id, 'amount': amount, 'currency': currency,
                'payment_method': p.get('method', 'cash'),
                'notes': 'دفعة مسجلة عبر المساعد الذكي',
                'user_id': getattr(user, 'id', None),
            })
            return {'executed': True,
                    'response': f'✅ تم استلام **{amount} درهم** من {cust.name}.', 'needs_clarification': False}

        if tool == 'create_expense':
            exp = cmd.create_expense(description=p.get('description', 'مصروف عبر المساعد'),
                                     amount=_dec(p.get('amount')), user_id=getattr(user, 'id', None))
            return {'executed': True, 'response': f'✅ تم تسجيل المصروف **{exp.description}** ({p.get("amount")} درهم).', 'needs_clarification': False}

        if tool == 'create_purchase':
            supp = _find_supplier(user, p.get('supplier_name'))
            if not supp:
                return {'executed': False, 'response': f'🔍 المورد «{p.get("supplier_name")}» غير موجود.', 'needs_clarification': True}
            prod = _find_product(user, p.get('product_name'))
            if not prod:
                return {'executed': False, 'response': f'🔍 المنتج «{p.get("product_name")}» غير موجود.', 'needs_clarification': True}
            qty = _dec(p.get('quantity', 1))
            cost = _dec(p.get('unit_cost', p.get('amount', 0)))
            pur = cmd.create_purchase(supplier_id=supp.id, product_id=prod.id, quantity=qty,
                                      unit_cost=cost, user_id=getattr(user, 'id', None))
            return {'executed': True,
                    'response': f'✅ تم تسجيل مشتريات #{getattr(pur, "id", "?")} من {supp.name}.', 'needs_clarification': False}

        if tool == 'create_cheque':
            from datetime import date
            ch = cmd.create_cheque(cheque_number=p.get('cheque_number'),
                                   amount=_dec(p.get('amount')),
                                   due_date=None, cheque_type=p.get('cheque_type', 'postdated'),
                                   user_id=getattr(user, 'id', None))
            return {'executed': True, 'response': f'✅ تم تسجيل الشيك **{ch.cheque_number}**.', 'needs_clarification': False}

        if tool == 'set_customer_balance':
            cust = _find_customer(user, p.get('customer_name'))
            if not cust:
                return {'executed': False, 'response': f'🔍 العميل «{p.get("customer_name")}» غير موجود.', 'needs_clarification': True}
            from services.payment_service import PaymentService
            PaymentService.adjust_customer_balance(
                customer=cust, new_balance=_dec(p.get('new_balance')),
                reason=p.get('reason') or 'تصحيح رصيد عبر المساعد الذكي',
                user_id=getattr(user, 'id', None))
            return {'executed': True,
                    'response': f'✅ تم تصحيح رصيد **{cust.name}** إلى {p.get("new_balance")} درهم.', 'needs_clarification': False}

        return {'executed': False, 'response': f'⚠️ أداة غير مدعومة للتنفيذ المباشر: {tool}', 'needs_clarification': False}
    except ValueError as e:
        return {'executed': False, 'response': f'⛔ {e}', 'needs_clarification': False}
    except Exception as e:  # noqa: BLE001
        return {'executed': False, 'response': f'⛔ تعذّر التنفيذ: {e}', 'needs_clarification': False}