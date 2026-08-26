from datetime import datetime, timezone
from extensions import db
from models.tenant_scope import TenantScopedMixin


class GLAccount(db.Model):
    __tablename__ = 'gl_accounts'

    # طبيعة الحساب: الأصول والمصروفات مدينة (طبيعية مدينة)،
    # الخصوم وحقوق الملكية والإيرادات دائنة (طبيعية دائنة).
    DEBIT_NATURE_TYPES = frozenset({'asset', 'expense'})
    CREDIT_NATURE_TYPES = frozenset({'liability', 'equity', 'revenue'})

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)  # English name
    name_ar = db.Column(db.String(200))  # Arabic name
    parent_id = db.Column(db.Integer, db.ForeignKey('gl_accounts.id'))
    type = db.Column(db.String(20), nullable=False, index=True)  # asset, liability, equity, revenue, expense
    currency = db.Column(db.String(3), default='ILS', nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_header = db.Column(db.Boolean, default=False)  # حساب رئيسي (لا يقبل قيود مباشرة)
    level = db.Column(db.Integer, default=0)  # مستوى الحساب في الشجرة
    description = db.Column(db.Text)  # وصف الحساب
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    parent = db.relationship('GLAccount', remote_side=[id], backref='children')

    def __repr__(self):
        return f'<GLAccount {self.code} {self.name}>'

    @property
    def full_name(self):
        """الاسم الكامل مع الكود"""
        return f"{self.code} - {self.name_ar or self.name}"

    @property
    def full_path(self):
        """المسار الهرمي الكامل (من الجذر إلى هذا الحساب) — إضافي لا يغيّر full_name"""
        chain = []
        seen = set()
        node = self
        while node is not None and node.id not in seen:
            seen.add(node.id)
            chain.append(node.code)
            node = node.parent
        return ' / '.join(reversed(chain))

    @property
    def is_debit_nature(self):
        """True للحسابات ذات الطبيعة المدينة (أصول/مصروفات)"""
        return self.type in GLAccount.DEBIT_NATURE_TYPES

    @property
    def type_ar(self):
        """نوع الحساب بالعربي"""
        types = {
            'asset': 'أصول',
            'liability': 'خصوم',
            'equity': 'حقوق ملكية',
            'revenue': 'إيرادات',
            'expense': 'مصروفات'
        }
        return types.get(self.type, self.type)

    @staticmethod
    def _as_bound_datetime(value, end_of_day=False):
        """تطبيع حدود التاريخ للمقارنة مع entry_date (DateTime)."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return None
        # كائن date (بدون وقت): بداية اليوم أو نهايته حسب الحد
        if end_of_day:
            return datetime(value.year, value.month, value.day, 23, 59, 59, 999999)
        return datetime(value.year, value.month, value.day)

    def _signed_balance_query(self, date_from=None, date_to=None, as_of_date=None):
        """استعلام مجموع amount_base مع فلاتر التاريخ (بدون تطبيق الإشارة)."""
        from sqlalchemy import func
        from models import GLJournalEntry, GLJournalLine

        q = db.session.query(func.sum(GLJournalLine.amount_base)).join(
            GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id
        ).filter(GLJournalLine.account_id == self.id)

        lower = self._as_bound_datetime(date_from, end_of_day=False)
        upper = self._as_bound_datetime(date_to, end_of_day=True) or self._as_bound_datetime(as_of_date, end_of_day=True)
        if lower is not None:
            q = q.filter(GLJournalEntry.entry_date >= lower)
        if upper is not None:
            q = q.filter(GLJournalEntry.entry_date <= upper)
        return q

    def get_balance(self, date_from=None, date_to=None, as_of_date=None):
        """حساب رصيد الحساب بالعملة المحلية.

        طبيعة الرصيد: الأصول/المصروفات مدينة (مدين - دائن)،
        الخصوم/حقوق الملكية/الإيرادات دائنة (دائن - مدين).

        يدعم اختيارياً:
        - date_from/date_to: رصيد فترة محددة.
        - as_of_date: الرصيد التراكمي حتى تاريخ معين (شامل).
        الاستدعاء بلا وسائط يحافظ على السلوك السابق تماماً.
        """
        balance_sum = self._signed_balance_query(
            date_from=date_from, date_to=date_to, as_of_date=as_of_date
        ).scalar()

        if balance_sum is None:
            return 0
        if self.is_debit_nature:
            return balance_sum
        return -balance_sum

    def get_descendants(self, active_only=True):
        """جميع الحسابات الفرعية (كل المستويات) — مسح تكراري آمن ضد الدورات."""
        result = []
        seen = {self.id}
        stack = list(self.children)
        while stack:
            child = stack.pop(0)
            if child.id in seen:
                continue  # حماية من المراجع الدائرية
            seen.add(child.id)
            if active_only and not child.is_active:
                continue  # تجاهل الفرع غير النشط بأكمله
            result.append(child)
            stack.extend(child.children)
        return result

    def get_children_recursive(self):
        """الحصول على جميع الحسابات الفرعية بشكل متكرر (سلوك تاريخي محفوظ)"""
        result = []
        for child in self.children:
            result.append(child)
            result.extend(child.get_children_recursive())
        return result

    def get_aggregate_balance(self, date_from=None, date_to=None, as_of_date=None,
                              include_self=True, active_only=False):
        """الرصيد الإجمالي: هذا الحساب + كل فروعه (parent = sum(children)).

        يطبق طبيعة كل حساب (مدين/دائن) على مجموعه قبل الجمع، عبر استعلام
        واحد مجمع حسب نوع الحساب.
        """
        from sqlalchemy import func
        from models import GLJournalEntry, GLJournalLine

        ids = [self.id] if include_self else []
        seen = {self.id}
        for desc in self.get_descendants(active_only=active_only):
            if desc.id not in seen:
                seen.add(desc.id)
                ids.append(desc.id)

        q = db.session.query(
            GLAccount.type, func.sum(GLJournalLine.amount_base)
        ).join(
            GLJournalLine, GLJournalLine.account_id == GLAccount.id
        ).join(
            GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id
        ).filter(GLAccount.id.in_(ids))

        lower = self._as_bound_datetime(date_from, end_of_day=False)
        upper = self._as_bound_datetime(date_to, end_of_day=True) or self._as_bound_datetime(as_of_date, end_of_day=True)
        if lower is not None:
            q = q.filter(GLJournalEntry.entry_date >= lower)
        if upper is not None:
            q = q.filter(GLJournalEntry.entry_date <= upper)

        total = None
        for acc_type, raw_sum in q.group_by(GLAccount.type).all():
            if raw_sum is None:
                continue
            signed = raw_sum if acc_type in GLAccount.DEBIT_NATURE_TYPES else -raw_sum
            total = signed if total is None else total + signed
        return total if total is not None else 0


class GLJournalEntry(TenantScopedMixin, db.Model):
    __tablename__ = 'gl_journal_entries'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    entry_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    entry_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    description = db.Column(db.String(255))
    reference_type = db.Column(db.String(50))  # sale, purchase, payment, expense, manual, adjustment, closing, reversing
    reference_id = db.Column(db.Integer)
    entry_type = db.Column(db.String(30), default='manual')  # manual, auto, adjustment, closing, reversing
    currency = db.Column(db.String(3), default='ILS', nullable=False)
    exchange_rate = db.Column(db.Numeric(15, 6), default=1)
    total_debit = db.Column(db.Numeric(18, 3), default=0)
    total_credit = db.Column(db.Numeric(18, 3), default=0)
    is_posted = db.Column(db.Boolean, default=True)  # هل تم ترحيل القيد
    is_reversed = db.Column(db.Boolean, default=False)  # هل تم عكس القيد
    reversed_entry_id = db.Column(db.Integer, db.ForeignKey('gl_journal_entries.id'))  # القيد المعكوس
    notes = db.Column(db.Text)  # ملاحظات إضافية
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    lines = db.relationship('GLJournalLine', back_populates='entry', lazy='dynamic', cascade='all, delete-orphan')
    reversed_entry = db.relationship('GLJournalEntry', remote_side=[id], foreign_keys=[reversed_entry_id])
    user = db.relationship('User', foreign_keys=[created_by])

    def __repr__(self):
        return f'<GLEntry {self.entry_number}>'

    def is_balanced(self):
        """Check if entry is balanced"""
        return self.total_debit == self.total_credit

    @property
    def entry_type_ar(self):
        """نوع القيد بالعربي"""
        types = {
            'manual': 'قيد يدوي',
            'auto': 'قيد تلقائي',
            'adjustment': 'قيد تسوية',
            'closing': 'قيد إقفال',
            'reversing': 'قيد عكسي'
        }
        return types.get(self.entry_type, self.entry_type)

    def reverse_entry(self, description=None):
        """عكس القيد (إنشاء قيد معاكس)"""
        if self.is_reversed:
            raise ValueError('هذا القيد تم عكسه مسبقاً')

        # إنشاء قيد معكوس  # noqa: E303
        y = datetime.now().strftime('%Y')
        from models import GLJournalEntry as _JE
        latest = db.session.query(_JE).filter(_JE.entry_number.like(f'JE-{y}-%')).order_by(_JE.entry_number.desc()).first()
        last_db = 0
        if latest:
            try:
                last_db = int(latest.entry_number.split('-')[-1])
            except Exception:
                last_db = 0
        next_num = last_db + 1
        reversed_entry = GLJournalEntry(
            entry_number=f'JE-{y}-{next_num:04d}',
            entry_date=datetime.now(timezone.utc),
            description=description or f'عكس قيد: {self.description}',
            reference_type=self.reference_type,
            reference_id=self.reference_id,
            entry_type='reversing',
            currency=self.currency,
            exchange_rate=self.exchange_rate,
            total_debit=self.total_credit,
            total_credit=self.total_debit,
            reversed_entry_id=self.id
        )
        db.session.add(reversed_entry)
        db.session.flush()

        # عكس السطور
        for line in self.lines:
            reversed_line = GLJournalLine(
                entry_id=reversed_entry.id,
                account_id=line.account_id,
                description=line.description,
                debit=line.credit,  # عكس
                credit=line.debit,  # عكس
                amount_base=-line.amount_base  # عكس
            )
            db.session.add(reversed_line)

        # تحديث القيد الأصلي
        self.is_reversed = True

        db.session.flush()
        return reversed_entry


class GLJournalLine(db.Model):
    __tablename__ = 'gl_journal_lines'

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('gl_journal_entries.id'), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('gl_accounts.id'), nullable=False, index=True)
    description = db.Column(db.String(255))
    debit = db.Column(db.Numeric(18, 3), default=0)
    credit = db.Column(db.Numeric(18, 3), default=0)
    amount_base = db.Column(db.Numeric(18, 3), default=0)

    # مركز التكلفة (اختياري)
    cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'))

    entry = db.relationship('GLJournalEntry', back_populates='lines')
    account = db.relationship('GLAccount')
    cost_center = db.relationship('CostCenter')

    def __repr__(self):
        return f'<GLLine acc={self.account_id} d={self.debit} c={self.credit}>'
