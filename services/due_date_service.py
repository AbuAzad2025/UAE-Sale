"""
خدمة تواريخ الاستحقاق - Due Date Service
=========================================

**المصدر الوحيد** لتاريخ استحقاق فاتورة البيع أو الشراء، ومنه تُشتق
شرائح التأخير (overdue) التي يقوم عليها تحليل أعمار الذمم المدينة والدائنة.

كان تحليل الأعمار يقيس **عمر** الفاتورة (الفرق بين تاريخها وتاريخ
التقرير) لا **ما هو مستحقّ فعلاً**، لأن جدولي `sales` و`purchases` لم
يحتويـا تاريخ استحقاق أصلاً، ولم يستعمل `payment_terms_days` — وهو مخزَّن
في الموردين منذ زمان — في أي مكان. ففاتورة عمرها 30 يوماً لم تستحق بعد
وفاتورة عمرها 30 يوماً متأخرة 30 يوماً كانتا في الشريحة نفسها.

القاعدة المعتمدة هنا:

  • تاريخ استحقاق **صريح** ⇒ هو المرجع دائماً (يتقدّم على الشروط).
  • وإلا ⇒ تاريخ الفاتورة + شروط الدفع (بالأيام) للعميل/المورد.
  • شروط 0 ⇒ الاستحقاق في تاريخ الفاتورة نفسه (مستحقّ فوراً).
  • فاتورة بلا تاريخ ⇒ لا استحقاق (`None`).
  • فاتورة بلا تاريخ استحقاق ⇒ تُعامل كأنها مستحقّة في تاريخها (وهو
    ما ترجّبه ترحيل البيانات `b1_due_dates`).

الشرائح (أيام التأخير عن تاريخ الاستحقاق):

    not_due  : لم يحن الاستحقاق بعد
    1-30     : تأخير من يوم إلى 30 يوماً
    31-60    : تأخير من 31 إلى 60 يوماً
    61-90    : تأخير من 61 إلى 90 يوماً
    90+      : تأخير يتجاوز 90 يوماً
"""

from datetime import date, datetime, timedelta, timezone


# شرائح التأخير — المصدر الوحيد لترتيب الشرائح في كل الشاشات والتقارير
OVERDUE_BUCKETS = ('not_due', '1-30', '31-60', '61-90', '90+')


def _to_date(value):
    """تطبيع قيمة إلى `date` (يقبل `date` و`datetime` ونص ISO).

    الأعمدة `sale_date` و`purchase_date` من نوع DateTime، وتاريخ
    الاستحقاق من نوع Date، فالتطبيع هنا يمنع خلط النوعين.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.strptime(text[:10], '%Y-%m-%d').date()
        except ValueError:
            return None
    return None


def _terms_days(party):
    """أيام شروط الدفع للطرف المقابل (0 عند غياب الطرف أو السمة)."""
    if party is None:
        return 0
    try:
        days = int(getattr(party, 'payment_terms_days', None) or 0)
    except (TypeError, ValueError):
        return 0
    return days if days > 0 else 0


def _derive_due_date(invoice_date, party, explicit):
    """اشتقاق تاريخ الاستحقاق — نفس المنطق للبيع والشراء."""
    explicit_date = _to_date(explicit)
    if explicit_date is not None:
        return explicit_date

    base = _to_date(invoice_date)
    if base is None:
        return None

    return base + timedelta(days=_terms_days(party))


def due_date_for_sale(sale_date, customer=None, explicit=None):
    """تاريخ استحقاق فاتورة البيع.

    Args:
        sale_date: تاريخ الفاتورة (DateTime أو Date أو نص ISO).
        customer: العميل (تُقرأ منه `payment_terms_days`).
        explicit: تاريخ استحقاق صريح — يتقدّم على شروط الدفع.

    Returns:
        date | None: تاريخ الاستحقاق، أو None إن لم يكن هناك تاريخ فاتورة.
    """
    return _derive_due_date(sale_date, customer, explicit)


def due_date_for_purchase(purchase_date, supplier=None, explicit=None):
    """تاريخ استحقاق فاتورة الشراء.

    Args:
        purchase_date: تاريخ الفاتورة (DateTime أو Date أو نص ISO).
        supplier: المورد (تُقرأ منه `payment_terms_days`).
        explicit: تاريخ استحقاق صريح — يتقدّم على شروط الدفع.

    Returns:
        date | None: تاريخ الاستحقاق، أو None إن لم يكن هناك تاريخ فاتورة.
    """
    return _derive_due_date(purchase_date, supplier, explicit)


def effective_due_date(due_date, invoice_date):
    """تاريخ الاستحقاق المعتمد لعرضه على المستند.

    فاتورة بلا تاريخ استحقاق تُعامل كأنها مستحقّة في تاريخها — وهو ما
    ترجّبه ترحيل البيانات `b1_due_dates` (backfill = تاريخ الفاتورة).
    """
    explicit = _to_date(due_date)
    if explicit is not None:
        return explicit
    return _to_date(invoice_date)


def overdue_days(due_date, as_of=None):
    """أيام التأخير عن تاريخ الاستحقاق.

    Args:
        due_date: تاريخ الاستحقاق (Date أو DateTime أو نص ISO أو None).
        as_of: تاريخ المرجع (افتراضياً اليوم بتوقيت UTC). خدمة الأعمار
            تمرّر تاريخها صراحةً (اليوم المحلي — نفس مرجع دفتر الأستاذ)
            فتبقى الشرائح متطابقة بين الشاشة والتقرير.

    Returns:
        int: 0 إن لم يوجد تاريخ استحقاق أو لم يحن بعد؛ وإلا عدد
            الأيام التي تجاوز فيها التأخير تاريخ الاستحقاق. تاريخ
            الاستحقاق المساوي لـ`as_of` ليس متأخراً بعد (0 يوم).
    """
    due = _to_date(due_date)
    if due is None:
        return 0

    reference = _to_date(as_of) if as_of is not None else None
    if reference is None:
        reference = datetime.now(timezone.utc).date()

    days = (reference - due).days
    return days if days > 0 else 0


def bucket_for_overdue(days):
    """تصنيف أيام التأخير إلى شريحة.

    Args:
        days: عدد أيام التأخير (0 أو أقل = لم يتأخر بعد).

    Returns:
        str: أحد `OVERDUE_BUCKETS`.
    """
    try:
        value = int(days)
    except (TypeError, ValueError):
        return 'not_due'

    if value <= 0:
        return 'not_due'
    if value <= 30:
        return '1-30'
    if value <= 60:
        return '31-60'
    if value <= 90:
        return '61-90'
    return '90+'
