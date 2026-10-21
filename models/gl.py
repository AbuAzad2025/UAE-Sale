from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import event, inspect
from sqlalchemy.orm import validates

from extensions import db
from models.tenant_scope import TenantScopedMixin


# ===========================================================================
# تسلسل أرقام القيود — تسلسل عالمي (ليس لكل مستأجر)
# ===========================================================================

def next_global_entry_number() -> str:
    """Return the next ``JE-YYYY-NNNN`` number from a GLOBAL sequence.

    ``gl_journal_entries.entry_number`` carries a table-wide UNIQUE
    constraint, therefore the sequence that produces it must be global: a
    tenant-scoped "max + 1" makes two tenants compute the SAME number and
    the second INSERT dies with an IntegrityError.

    ``utils.helpers.generate_number`` already takes a distributed lock, but
    it reads the maximum through the ORM, and the ORM query is rewritten by
    the tenant filter. The tenant scope is therefore suspended for the
    duration of the (locked) lookup only, so the maximum is computed over
    the whole table. The scope is restored immediately afterwards.
    """
    from models.tenant_scope import get_current_tenant_id, set_current_tenant_id
    from utils.helpers import generate_number

    current_tenant = get_current_tenant_id()
    if current_tenant is not None:
        # مؤقتاً فقط: التسلسل عام وليس خاصاً بالمستأجر
        set_current_tenant_id(None)
    try:
        return generate_number('JE', GLJournalEntry, field_name='entry_number')
    finally:
        if current_tenant is not None:
            set_current_tenant_id(current_tenant)


class GLAccount(db.Model):
    __tablename__ = 'gl_accounts'

    # طبيعة الحساب: الأصول والمصروفات مدينة (طبيعية مدينة)،
    # الخصوم وحقوق الملكية والإيرادات دائنة (طبيعية دائنة).
    DEBIT_NATURE_TYPES = frozenset({'asset', 'expense'})
    CREDIT_NATURE_TYPES = frozenset({'liability', 'equity', 'revenue'})

    # F8: أنواع الحساب المسموحة فقط — أي قيمة أخرى (خطأ مطبعي مثل 'banana')
    # كانت تُخزَّن بصمت وتُعامل كحساب دائن الطبيعة (إشارة خاطئة).
    VALID_TYPES = frozenset({'asset', 'liability', 'equity', 'revenue', 'expense'})

    # F8: أكواد دليل الحسابات الأساسي (المُبذَر بواسطة ensure_core_accounts).
    # تُستخدم للتحقق من الاتجاه ولحماية الحسابات المُبذَرة من التعديل،
    # حتى قبل وصول عمود is_system إلى قاعدة البيانات (م-see تقرير الترحيل).
    CORE_CODES = frozenset({
        '1000', '1100', '1110', '1120', '1121', '1130', '1140', '1150',
        '1200', '1210', '1220', '1230', '1240', '1250',
        '2000', '2100', '2110', '2115', '2120', '2130', '2140',
        '2200', '2210',
        '3000', '3100', '3200', '3300', '3350', '3400',
        '4000', '4100', '4200', '4300', '4400', '4500',
        '5000', '5100', '5150', '5200', '5300',
        '6000', '6100', '6200', '6300', '6400', '6500', '6600', '6700',
        '6800', '6900', '6950', '6990',
    })

    # F8: الاستثناءات الموثّقة لحركة مدين على حساب طبيعيته دائنة.
    # كل استثناء له سبب محاسبي حقيقي في كود المشروع الحالي.
    DEBIT_ALLOWED_ON_CREDIT_NORMAL = {
        '2110': 'سداد الموردين: مدين على الذمم الدائنة عند التسديد',
        '2115': 'سداد ذمم التجار',
        '2120': 'صرف شيك مؤجل الدفع (مدين على شيكات مؤجلة الدفع)',
        '2130': 'ضريبة مدخلات على المشتريات وعكس ضريبة المخرجات عند المرتجع',
        '2140': 'صرف الرواتب المستحقة',
        '2210': 'سداد القروض',
        '3300': 'مسحوبات المالك (مدين على جاري المالك)',
        '3350': 'مسحوبات الشركاء',
        '3400': 'إقفال أرباح السنة الحالية',
        '4100': 'مردودات المبيعات: حساب مرافق للإيراد (AccountRole.SALES_RETURNS)',
    }

    # F8: الاستثناءات الموثّقة لحركة دائن على حساب طبيعيته مدينة.
    # الأصول تنقص بالدائن (صرف/بيع/تحصيل) والمصروفات تُعكس بالدائن.
    CREDIT_ALLOWED_ON_DEBIT_NORMAL = {
        '1110': 'سحب نقدي من الصندوق',
        '1120': 'صرف من البنك',
        '1121': 'صرف من حساب التوفير',
        '1130': 'تحصيل ذمم مدينة / مرتجع مبيعات',
        '1140': 'صرف المخزون عند البيع (تكلفة المبيعات)',
        '1150': 'تحصيل أو ارتداد شيك تحت التحصيل',
        '1210': 'استبعاد أصل ثابت',
        '1220': 'استبعاد أصل ثابت',
        '1230': 'استبعاد أصل ثابت',
        '1240': 'استبعاد أصل ثابت',
        '1250': 'استبعاد أصل ثابت',
        '5100': 'عكس تكلفة المبيعات عند المرتجع',
        '5150': 'عكس قيد تعديل المخزون',
        '5200': 'عكس الخصومات الممنوحة',
        '5300': 'عكس مصروف الشحن',
        '6100': 'عكس مصروف الرواتب',
        '6200': 'عكس مصروف الإيجار',
        '6300': 'عكس مصروف الكهرباء والماء',
        '6400': 'عكس مصروف الصيانة',
        '6500': 'عكس مصروف التسويق',
        '6600': 'عكس مصروف المواصلات',
        '6700': 'عكس مصروف الاتصالات',
        '6800': 'عكس مصروف القرطاسية',
        '6900': 'عكس خسارة فرق العملة',
        '6950': 'عكس المصروفات البنكية',
        '6990': 'عكس المصروفات المتنوعة',
    }

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
    # F8: حساب مُبذَر من دليل الحسابات الأساسي — لا يُعدَّل كوده/نوعه ولا يُحذف.
    # (requires a migration — see report)
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    parent = db.relationship('GLAccount', remote_side=[id], backref='children')

    def __repr__(self):
        return f'<GLAccount {self.code} {self.name}>'

    # ------------------------------------------------------------------
    # F8 — التحقق من صحة نوع الحساب
    # ------------------------------------------------------------------

    @validates('type')
    def _validate_type(self, key, value):
        """يرفض أي نوع خارج القائمة المسموحة (خطأ مطبعي = إشارة خاطئة صامتة)."""
        if value is None:
            raise ValueError('نوع الحساب مطلوب')
        normalized = str(value).strip().lower()
        if normalized not in GLAccount.VALID_TYPES:
            valid = ', '.join(sorted(GLAccount.VALID_TYPES))
            raise ValueError(
                f'نوع حساب غير صالح: {value!r}. الأنواع المسموحة: {valid}'
            )
        return normalized

    @property
    def is_core_account(self):
        """True إذا كان الحساب من دليل الحسابات الأساسي (المُبذَر)."""
        return (self.code in GLAccount.CORE_CODES) or bool(
            getattr(self, 'is_system', False)
        )

    @property
    def is_locked(self):
        """حساب مُقفل: لا يُعدَّل كوده/نوعه ولا يُحذف."""
        return self.is_core_account

    # ------------------------------------------------------------------
    # F8 — التحقق من اتجاه الحركة
    # ------------------------------------------------------------------

    def check_posting_direction(self, debit, credit):
        """يرفض الحركة في الاتجاه المعاكس لطبيعة الحساب.

        - حساب طبيعيته مدينة (أصول/مصروفات): الحركة المدينة هي الطبيعية،
          والدائن مسموح فقط للاستثناءات الموثّقة (نقص الأصل/عكس المصروف).
        - حساب طبيعيته دائنة (خصوم/حقوق ملكية/إيرادات): الحركة الدائنة هي
          الطبيعية، والمدين مسموح فقط للاستثناءات الموثّقة (السداد،
          المسحوبات، المردودات).

        يُطبَّق الفحص على دليل الحسابات الأساسي فقط؛ الحسابات المخصصة قد
        تكون حسابات مرافقة (مثل مجمع الإهلاك الثابت) طبيعتها مختلفة.
        """
        debit = Decimal(str(debit or 0))
        credit = Decimal(str(credit or 0))
        if debit <= 0 and credit <= 0:
            return
        if debit > 0 and credit > 0:
            raise ValueError(
                f'سطر القيد لا يحمل مديناً ودائناً في آن واحد ({self.full_name})'
            )

        if not self.is_core_account:
            return

        if debit > 0 and not self.is_debit_nature:
            reason = GLAccount.DEBIT_ALLOWED_ON_CREDIT_NORMAL.get(self.code)
            if reason is None:
                raise ValueError(
                    f'لا يُسمح بترحيل مدين على حساب دائن الطبيعة: '
                    f'{self.full_name} (نوع الحساب: {self.type})'
                )
            return

        if credit > 0 and self.is_debit_nature:
            reason = GLAccount.CREDIT_ALLOWED_ON_DEBIT_NORMAL.get(self.code)
            if reason is None:
                raise ValueError(
                    f'لا يُسمح بترحيل دائن على حساب مدين الطبيعة: '
                    f'{self.full_name} (نوع الحساب: {self.type})'
                )
            return

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
        """Convert date/string to datetime for query bounds."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            if end_of_day:
                return datetime(value.year, value.month, value.day, 23, 59, 59, 999999)
            return datetime(value.year, value.month, value.day)
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return None
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
                continue  # تجاهل الفرع غير النشط بالكامل
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

    # F9: حالة القيد — مسودة (غير مرحّل) أو مرحّل.
    STATE_DRAFT = False
    STATE_POSTED = True

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
    # F9: حالة صريحة — كل مسار الإنشاء في طبقة الخدمات يمرّرها صراحةً.
    # القيم الافتراضية تبقى True لRows التي تُنشأ مباشرة عبر ORM.
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

    def reverse_entry(self, description=None, entry_date=None, created_by=None):
        """عكس القيد (إنشاء قيد معاكس).

        F2: كان يولّد رقم القيد العكسي يدوياً (max+1) بدون قفل موزّع،
        ولا يكتب سجل تدقيق، ولا يربط القيدين في الاتجاهين. الآن:
        - الرقم يأتي من ``next_global_entry_number`` (قفل موزّع + تسلسل عام)،
        - الربط في الاتجاهين: ``original.reversed_entry_id`` و
          ``reversal.reversed_entry_id``،
        - يُكتب سجل تدقيق للقيد العكسي،
        - إجماليات القيد العكسي تُشتق من السطور التي يكتبها (لا من إجماليات
          القيد الأصلي، فقد لا يكون القيد الأصلي متسقاً داخلياً).
        """
        if self.is_reversed:
            raise ValueError('هذا القيد تم عكسه مسبقاً')

        entry_date = entry_date or datetime.now(timezone.utc)
        entry_number = next_global_entry_number()

        # قراءة سطور القيد الأصلي أولاً: الإجماليات تُشتق من السطور التي
        # ستُكتب (وليس من إجماليات الرأس، فقد لا يكون القيد متسقاً داخلياً).
        source_lines = [
            (line.account, line.account_id, line.description,
             Decimal(str(line.debit or 0)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP),
             Decimal(str(line.credit or 0)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP),
             Decimal(str(line.amount_base or 0)))
            for line in self.lines
        ]

        total_debit = Decimal('0')
        total_credit = Decimal('0')
        for _account, _account_id, _description, _debit, _credit, _amount_base in source_lines:
            total_debit += _credit
            total_credit += _debit

        reversed_entry = GLJournalEntry(
            entry_number=entry_number,
            entry_date=entry_date,
            description=description or f'عكس قيد: {self.description}',
            reference_type=self.reference_type,
            reference_id=self.reference_id,
            entry_type='reversing',
            currency=self.currency,
            exchange_rate=self.exchange_rate,
            total_debit=total_debit,
            total_credit=total_credit,
            is_posted=GLJournalEntry.STATE_POSTED,
            # F2 — الربط في الاتجاهين: القيد العكسي يشير إلى الأصل.
            reversed_entry_id=self.id,
            created_by=created_by if created_by is not None else self.created_by,
            tenant_id=self.tenant_id,
        )
        db.session.add(reversed_entry)

        # عكس السطور
        for account, account_id, description_line, debit, credit, amount_base in source_lines:
            db.session.add(GLJournalLine(
                entry=reversed_entry,
                account=account,
                account_id=account_id,
                description=description_line,
                debit=credit,  # عكس
                credit=debit,  # عكس
                amount_base=-amount_base,  # عكس
                tenant_id=getattr(self, 'tenant_id', None),
            ))

        # INSERT واحد (رأس + سطور) — لا تعديل على قيد مرحّل بعد إنشائه.
        db.session.flush()

        # تحديث القيد الأصلي — الربط في الاتجاهين.
        self.is_reversed = True
        self.reversed_entry_id = reversed_entry.id

        db.session.flush()

        # سجل التدقيق (F2) — القيد العكسي لا بد أن يكون معتمَداً.
        try:
            from models.journal_entry_audit import JournalEntryAudit

            JournalEntryAudit.record(
                journal_entry_id=reversed_entry.id,
                action=JournalEntryAudit.ACTION_REVERSE,
                old_values=None,
                new_values=JournalEntryAudit.entry_payload(reversed_entry),
                reason=f'عكس القيد {self.entry_number}',
                performed_by=created_by,
                fallback_entry=self,
            )
            db.session.flush()
        except Exception:  # pragma: no cover - لا يُفشل العكس بسبب التدقيق
            import logging

            logging.getLogger(__name__).error(
                'Failed to write reversal audit for entry %s', self.entry_number,
                exc_info=True,
            )

        return reversed_entry


class GLJournalLine(TenantScopedMixin, db.Model):
    __tablename__ = 'gl_journal_lines'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
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


# ===========================================================================
# F5 — حماية القيد المرحّل من التعديل المباشر عبر ORM
# ===========================================================================

# الحقول المالية/الثابتة التي لا يجوز تعديلها بعد ترحيل القيد.
# is_posted و is_reversed و reversed_entry_id و notes و updated_at ليست
# منها: انتقال المسودة↔المرحّل ورابط العكس meta-data وليس محتوى مالي.
IMMUTABLE_POSTED_FIELDS = (
    'entry_number',
    'entry_date',
    'description',
    'reference_type',
    'reference_id',
    'entry_type',
    'currency',
    'exchange_rate',
    'total_debit',
    'total_credit',
    'created_by',
    'tenant_id',
)


@event.listens_for(GLJournalEntry, 'before_update')
def _guard_posted_journal_entry(mapper, connection, target):
    """يمنع تعديل قيد مرحّل عبر ORM.

    models/events.py يسجّل مستمعاً للتحقق من التوازن لكنه يسجّل الخطأ
    فقط (الرفع معطّل)، فلم يكن هناك أي حاجز فعلي على مستوى ORM. هذا
    الحاجز يمنع تعديل المحتوى المالي لقيد مرحّل: العكس هو المسار الوحيد
    المسموح (وهو يغيّر is_reversed/reversed_entry_id فقط).
    """
    state = inspect(target)
    changed = []
    for attr in IMMUTABLE_POSTED_FIELDS:
        try:
            history = state.attrs[attr].history
        except Exception:
            continue
        if history.has_changes():
            changed.append(attr)
    if not changed:
        return

    posted_before = False
    try:
        history = state.attrs['is_posted'].history
        if history.deleted:
            posted_before = bool(history.deleted[0])
        else:
            posted_before = bool(getattr(target, 'is_posted', False))
    except Exception:
        posted_before = bool(getattr(target, 'is_posted', False))

    if not posted_before:
        # القيد مسودة: التعديل مسموح (مسار المسودة → الموافقة).
        return

    raise ValueError(
        f'القيد المرحّل غير قابل للتعديل ({target.entry_number}). '
        f'الحقول المحمية: {", ".join(changed)}. '
        'استخدم القيد العكسي (Reverse) بدلاً من التعديل.'
    )


@event.listens_for(GLAccount, 'before_update')
def _guard_system_account_update(mapper, connection, target):
    """F8: لا يُعدَّل كود/نوع حساب مُبذَر من دليل الحسابات الأساسي."""
    state = inspect(target)
    changed = []
    for attr in ('code', 'type'):
        try:
            history = state.attrs[attr].history
        except Exception:
            continue
        if history.has_changes():
            changed.append(attr)
    if not changed:
        return

    # القيود تُحسب على القيمة قبل التعديل: تغيير الكود يجب ألّا يفلت
    # من الحماية بأن يصبح الكود الجديد غير مُبذَر.
    old_code = target.code
    try:
        history = state.attrs['code'].history
        if history.deleted:
            old_code = history.deleted[0]
    except Exception:
        pass

    was_locked = (old_code in GLAccount.CORE_CODES) or bool(
        getattr(target, 'is_system', False)
    )
    if not was_locked:
        return
    raise ValueError(
        f'الحساب {old_code} حساب أساسي مُبذَر — لا يمكن تعديل '
        f'{", ".join(changed)}. '
    )


@event.listens_for(GLAccount, 'before_delete')
def _guard_system_account_delete(mapper, connection, target):
    """F8: لا يُحذف حساب مُبذَر من دليل الحسابات الأساسي."""
    if target.is_locked:
        raise ValueError(
            f'الحساب {target.code} حساب أساسي مُبذَر — لا يمكن حذفه. '
            'ألغِ تنشيطه بدلاً من حذفه.'
        )
