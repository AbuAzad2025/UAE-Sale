from decimal import Decimal
from datetime import datetime, timezone
from extensions import db
from models import GLAccount, GLJournalEntry, GLJournalLine
from services.currency_service import CurrencyService

_JE_SEQ = {}


class GLService:
    @staticmethod
    def ensure_core_accounts():
        """Create enhanced GL accounts with hierarchical structure"""
        # (code, name_ar, name_en, type, parent_code, is_header, level)
        core = [
            # === الأصول Assets ===
            ('1000', 'الأصول', 'Assets', 'asset', None, True, 0),
            ('1100', 'الأصول المتداولة', 'Current Assets', 'asset', '1000', True, 1),
            ('1110', 'الصندوق', 'Cash', 'asset', '1100', False, 2),
            ('1120', 'البنك - حساب جاري', 'Bank - Current Account', 'asset', '1100', False, 2),
            ('1121', 'البنك - حساب توفير', 'Bank - Savings Account', 'asset', '1100', False, 2),
            ('1130', 'الذمم المدينة', 'Accounts Receivable', 'asset', '1100', False, 2),
            ('1140', 'المخزون', 'Inventory', 'asset', '1100', False, 2),
            ('1150', 'شيكات تحت التحصيل', 'Cheques Under Collection', 'asset', '1100', False, 2),

            ('1200', 'الأصول الثابتة', 'Fixed Assets', 'asset', '1000', True, 1),
            ('1210', 'أراضي', 'Land', 'asset', '1200', False, 2),
            ('1220', 'مباني', 'Buildings', 'asset', '1200', False, 2),
            ('1230', 'سيارات', 'Vehicles', 'asset', '1200', False, 2),
            ('1240', 'معدات', 'Equipment', 'asset', '1200', False, 2),
            ('1250', 'أثاث', 'Furniture', 'asset', '1200', False, 2),

            # === الخصوم Liabilities ===
            ('2000', 'الخصوم', 'Liabilities', 'liability', None, True, 0),
            ('2100', 'الخصوم المتداولة', 'Current Liabilities', 'liability', '2000', True, 1),
            ('2110', 'الذمم الدائنة', 'Accounts Payable', 'liability', '2100', False, 2),
            ('2115', 'ذمم التجار', 'Merchants Payable', 'liability', '2100', False, 2),
            ('2120', 'شيكات مؤجلة الدفع', 'Deferred Cheques Payable', 'liability', '2100', False, 2),
            ('2130', 'ضرائب مستحقة', 'Taxes Payable', 'liability', '2100', False, 2),
            ('2140', 'رواتب مستحقة', 'Salaries Payable', 'liability', '2100', False, 2),

            ('2200', 'الخصوم طويلة الأجل', 'Long-term Liabilities', 'liability', '2000', True, 1),
            ('2210', 'قروض', 'Loans', 'liability', '2200', False, 2),

            # === حقوق الملكية Equity ===
            ('3000', 'حقوق الملكية', 'Equity', 'equity', None, True, 0),
            ('3100', 'رأس المال', 'Capital', 'equity', '3000', False, 1),
            ('3200', 'الأرباح المحتجزة', 'Retained Earnings', 'equity', '3000', False, 1),
            ('3300', 'جاري المالك', 'Owner Draw', 'equity', '3000', False, 1),
            ('3350', 'جاري الشركاء', 'Partners Current Account', 'equity', '3000', False, 1),
            ('3400', 'أرباح السنة الحالية', 'Current Year Profit', 'equity', '3000', False, 1),

            # === الإيرادات Revenues ===
            ('4000', 'الإيرادات', 'Revenues', 'revenue', None, True, 0),
            ('4100', 'إيرادات المبيعات', 'Sales Revenue', 'revenue', '4000', False, 1),
            ('4200', 'إيرادات الخدمات', 'Service Revenue', 'revenue', '4000', False, 1),
            ('4300', 'إيرادات الشحن', 'Shipping Revenue', 'revenue', '4000', False, 1),
            ('4400', 'أرباح فرق العملة', 'Foreign Exchange Gain', 'revenue', '4000', False, 1),
            ('4500', 'إيرادات أخرى', 'Other Revenue', 'revenue', '4000', False, 1),

            # === المصروفات Expenses ===
            ('5000', 'تكلفة المبيعات', 'Cost of Sales', 'expense', None, True, 0),
            ('5100', 'تكلفة البضاعة المباعة', 'Cost of Goods Sold', 'expense', '5000', False, 1),
            ('5150', 'تعديلات المخزون', 'Inventory Adjustments', 'expense', '5000', False, 1),
            ('5200', 'الخصومات الممنوحة', 'Discounts Given', 'expense', '5000', False, 1),
            ('5300', 'مصروفات الشحن', 'Shipping Expense', 'expense', '5000', False, 1),

            ('6000', 'المصروفات التشغيلية', 'Operating Expenses', 'expense', None, True, 0),
            ('6100', 'رواتب وأجور', 'Salaries & Wages', 'expense', '6000', False, 1),
            ('6200', 'إيجار', 'Rent', 'expense', '6000', False, 1),
            ('6300', 'كهرباء وماء', 'Utilities', 'expense', '6000', False, 1),
            ('6400', 'صيانة', 'Maintenance', 'expense', '6000', False, 1),
            ('6500', 'تسويق وإعلان', 'Marketing & Advertising', 'expense', '6000', False, 1),
            ('6600', 'مواصلات', 'Transportation', 'expense', '6000', False, 1),
            ('6700', 'اتصالات', 'Communications', 'expense', '6000', False, 1),
            ('6800', 'قرطاسية', 'Stationery', 'expense', '6000', False, 1),
            ('6900', 'خسائر فرق العملة', 'Foreign Exchange Loss', 'expense', '6000', False, 1),
            ('6950', 'مصروفات بنكية', 'Bank Charges', 'expense', '6000', False, 1),
            ('6990', 'مصروفات متنوعة', 'Miscellaneous Expenses', 'expense', '6000', False, 1),
        ]

        created_any = False
        created_cache = {}

        for code, name_ar, name_en, acc_type, parent_code, is_header, level in core:
            acc = GLAccount.query.filter_by(code=code).first()
            if acc:
                created_cache[code] = acc
                continue

            parent_id = None
            if parent_code:
                parent_acc = created_cache.get(parent_code) or GLAccount.query.filter_by(code=parent_code).first()
                if parent_acc:
                    parent_id = parent_acc.id

            acc = GLAccount(
                code=code,
                name=name_en,
                name_ar=name_ar,
                type=acc_type,
                parent_id=parent_id,
                is_header=is_header,
                level=level,
                currency='ILS'
            )
            db.session.add(acc)
            db.session.flush()
            created_cache[code] = acc
            created_any = True

        if created_any:
            db.session.flush()

    @staticmethod
    def get_payment_debit_account(method):
        m = (method or '').strip()
        if m == 'cash':
            return '1110'
        if m in ('bank_transfer', 'card'):
            return '1120'
        if m == 'cheque':
            return '1150'
        return '1110'

    @staticmethod
    def get_customer_credit_account(customer):
        code = '1130'
        if customer and getattr(customer, 'customer_type', None) == 'partner':
            code = '3350'
        elif customer and getattr(customer, 'customer_type', None) == 'merchant':
            code = '2115'
        return code

    @staticmethod
    def create_journal_entry(entry_type, description, lines, reference_type=None, reference_id=None):
        """
        Create a journal entry

        Args:
            entry_type (str): Type of entry (sale, purchase, payment, etc.)
            description (str): Entry description
            lines (list): List of journal lines [{'account_code': str, 'debit': Decimal, 'credit': Decimal}]
            reference_type (str): Optional reference type
            reference_id (int): Optional reference ID

        Returns:
            GLJournalEntry: Created journal entry

        Raises:
            ValueError: If entry is not balanced
        """
        from models import GLAccount, GLJournalEntry, GLJournalLine

        # Validate balance
        total_debit = sum(Decimal(str(line['debit'])) for line in lines)
        total_credit = sum(Decimal(str(line['credit'])) for line in lines)

        if total_debit != total_credit:
            raise ValueError(f"Journal entry is not balanced: Debit={total_debit}, Credit={total_credit}")

        # Generate entry number
        def _unique_entry_number():
            y = datetime.now().strftime('%Y')
            from models import GLJournalEntry as _JE
            latest = db.session.query(_JE).filter(_JE.entry_number.like(f'JE-{y}-%')).order_by(_JE.entry_number.desc()).first()
            last_db = 0
            if latest:
                try:
                    last_db = int(latest.entry_number.split('-')[-1])
                except Exception:
                    last_db = 0
            last_mem = _JE_SEQ.get(y, last_db)
            next_num = max(last_db, last_mem) + 1
            _JE_SEQ[y] = next_num
            return f'JE-{y}-{next_num:04d}'
        entry_number = _unique_entry_number()

        # Create entry
        GLService.ensure_core_accounts()

        entry = GLJournalEntry(
            entry_number=entry_number,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            total_debit=total_debit,
            total_credit=total_credit
        )
        db.session.add(entry)
        db.session.flush()

        # Create lines
        for line_data in lines:
            account = GLAccount.query.filter_by(code=line_data['account_code']).first()
            if not account:
                raise ValueError(f"Account {line_data['account_code']} not found")

            line = GLJournalLine(
                entry_id=entry.id,
                account_id=account.id,
                debit=Decimal(str(line_data['debit'])),
                credit=Decimal(str(line_data['credit'])),
                description=line_data.get('description', description)
            )
            db.session.add(line)

        db.session.commit()
        return entry

    @staticmethod
    def post_entry(lines, description='', reference_type=None, reference_id=None, currency=None, exchange_rate=1):
        currency = currency or CurrencyService.get_base_currency()

        def _unique_entry_number():
            y = datetime.now().strftime('%Y')
            from models import GLJournalEntry as _JE
            latest = db.session.query(_JE).filter(_JE.entry_number.like(f'JE-{y}-%')).order_by(_JE.entry_number.desc()).first()
            last_db = 0
            if latest:
                try:
                    last_db = int(latest.entry_number.split('-')[-1])
                except Exception:
                    last_db = 0
            last_mem = _JE_SEQ.get(y, last_db)
            next_num = max(last_db, last_mem) + 1
            _JE_SEQ[y] = next_num
            return f'JE-{y}-{next_num:04d}'
        entry_number = _unique_entry_number()
        entry = GLJournalEntry(
            entry_number=entry_number,
            entry_date=datetime.now(timezone.utc),
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            currency=currency,
            exchange_rate=Decimal(str(exchange_rate))
        )
        db.session.add(entry)
        db.session.flush()
        total_debit = Decimal('0')
        total_credit = Decimal('0')
        for ln in lines:
            account = ln['account'] if isinstance(ln['account'], GLAccount) else GLAccount.query.filter_by(code=ln['account']).first()
            if not account:
                GLService.ensure_core_accounts()
                account = GLAccount.query.filter_by(code=ln['account']).first()
            if not account:
                raise ValueError(f"GL account '{ln['account']}' not found while posting entry '{description}'")
            debit = Decimal(str(ln.get('debit', 0) or 0))
            credit = Decimal(str(ln.get('credit', 0) or 0))
            amount_base = (debit - credit) * Decimal(str(exchange_rate))
            db.session.add(GLJournalLine(
                entry=entry,
                account=account,
                description=ln.get('description'),
                debit=debit,
                credit=credit,
                amount_base=amount_base
            ))
            total_debit += debit
            total_credit += credit
        entry.total_debit = total_debit
        entry.total_credit = total_credit
        if total_debit != total_credit:
            raise ValueError('GL entry not balanced')
        db.session.flush()
        return entry

    @staticmethod
    def create_manual_entry(description, lines, entry_date=None, notes=None, created_by=None):
        """إنشاء قيد يدوي"""
        from flask_login import current_user

        def _unique_entry_number():
            y = datetime.now().strftime('%Y')
            from models import GLJournalEntry as _JE
            latest = db.session.query(_JE).filter(_JE.entry_number.like(f'JE-{y}-%')).order_by(_JE.entry_number.desc()).first()
            last_db = 0
            if latest:
                try:
                    last_db = int(latest.entry_number.split('-')[-1])
                except Exception:
                    last_db = 0
            last_mem = _JE_SEQ.get(y, last_db)
            next_num = max(last_db, last_mem) + 1
            _JE_SEQ[y] = next_num
            return f'JE-{y}-{next_num:04d}'
        entry_number = _unique_entry_number()

        total_debit = Decimal('0')
        total_credit = Decimal('0')

        # التحقق من التوازن
        for line in lines:
            total_debit += Decimal(str(line.get('debit', 0) or 0))
            total_credit += Decimal(str(line.get('credit', 0) or 0))

        if total_debit != total_credit:
            raise ValueError(f'القيد غير متوازن: مدين={total_debit}, دائن={total_credit}')

        # إنشاء القيد
        entry = GLJournalEntry(
            entry_number=entry_number,
            entry_date=entry_date or datetime.now(timezone.utc),
            description=description,
            entry_type='manual',
            notes=notes,
            total_debit=total_debit,
            total_credit=total_credit,
            created_by=created_by or (current_user.id if current_user.is_authenticated else None)
        )
        db.session.add(entry)
        db.session.flush()

        # إنشاء السطور
        for line_data in lines:
            account_code = line_data.get('account_code') or line_data.get('account')
            account = GLAccount.query.filter_by(code=account_code).first()

            if not account:
                raise ValueError(f'الحساب {account_code} غير موجود')

            if account.is_header:
                raise ValueError(f'الحساب {account.full_name} هو حساب رئيسي ولا يمكن إضافة قيود عليه')

            debit = Decimal(str(line_data.get('debit', 0) or 0))
            credit = Decimal(str(line_data.get('credit', 0) or 0))

            line = GLJournalLine(
                entry_id=entry.id,
                account_id=account.id,
                description=line_data.get('description', ''),
                debit=debit,
                credit=credit,
                amount_base=debit - credit
            )
            db.session.add(line)

        db.session.commit()
        return entry

    @staticmethod
    def get_account_statement(account_id, date_from=None, date_to=None):
        """كشف حساب تفصيلي"""
        from sqlalchemy import func

        account = db.get_or_404(GLAccount, account_id)

        query = GLJournalLine.query.filter_by(account_id=account_id).join(GLJournalEntry)

        if date_from:
            query = query.filter(func.date(GLJournalEntry.entry_date) >= date_from)

        if date_to:
            query = query.filter(func.date(GLJournalEntry.entry_date) <= date_to)

        lines = query.order_by(GLJournalEntry.entry_date).all()

        # حساب الرصيد الافتتاحي (فقط عند وجود تاريخ بداية،
        # وإلا فالافتتاحي صفر لتفادي الاحتساب المزدوج)
        opening_debit_q = db.session.query(func.sum(GLJournalLine.debit)).filter(
            GLJournalLine.account_id == account_id
        ).join(GLJournalEntry)
        opening_credit_q = db.session.query(func.sum(GLJournalLine.credit)).filter(
            GLJournalLine.account_id == account_id
        ).join(GLJournalEntry)

        if date_from:
            opening_debit_q = opening_debit_q.filter(func.date(GLJournalEntry.entry_date) < date_from)
            opening_credit_q = opening_credit_q.filter(func.date(GLJournalEntry.entry_date) < date_from)
        else:
            # بلا تاريخ بداية: كل القيود ضمن الفترة، الافتتاحي صفر
            opening_debit_q = opening_debit_q.filter(db.false())
            opening_credit_q = opening_credit_q.filter(db.false())

        opening_debit = opening_debit_q.scalar() or Decimal('0')
        opening_credit = opening_credit_q.scalar() or Decimal('0')

        # حساب الرصيد بناءً على نوع الحساب
        if account.type in ['asset', 'expense']:
            opening_balance = opening_debit - opening_credit
        else:  # liability, equity, revenue
            opening_balance = opening_credit - opening_debit

        # إنشاء كشف الحساب
        running_balance = opening_balance
        transactions = []

        for line in lines:
            if account.type in ['asset', 'expense']:
                running_balance += line.debit - line.credit
            else:
                running_balance += line.credit - line.debit

            transactions.append({
                'date': line.entry.entry_date,
                'entry_number': line.entry.entry_number,
                'entry_type': line.entry.entry_type_ar,
                'description': line.description or line.entry.description,
                'reference': f'{line.entry.reference_type} #{line.entry.reference_id}' if line.entry.reference_type else '',
                'debit': float(line.debit),
                'credit': float(line.credit),
                'balance': float(running_balance)
            })

        return {
            'account': account,
            'opening_balance': float(opening_balance),
            'transactions': transactions,
            'closing_balance': float(running_balance),
            'total_debit': sum(t['debit'] for t in transactions),
            'total_credit': sum(t['credit'] for t in transactions)
        }

    @staticmethod
    def get_accounts_tree():
        """الحصول على شجرة الحسابات"""
        # الحصول على الحسابات الرئيسية (بدون parent)
        root_accounts = GLAccount.query.filter_by(parent_id=None, is_active=True).order_by(GLAccount.code).all()

        def build_tree(account):
            """بناء الشجرة بشكل متكرر"""
            return {
                'id': account.id,
                'code': account.code,
                'name': account.name,
                'name_ar': account.name_ar,
                'full_name': account.full_name,
                'type': account.type,
                'type_ar': account.type_ar,
                'is_header': account.is_header,
                'level': account.level,
                'balance': float(account.get_balance()),
                'children': [build_tree(child) for child in account.children if child.is_active]
            }

        return [build_tree(acc) for acc in root_accounts]
