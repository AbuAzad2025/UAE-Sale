"""توزيع أرباح الشركاء — على مستويين:

مستوى المنتج (ProductPartner):
  عند ترحيل الفاتورة يُحسب ربح كل سطر = (صافي سعر البيع + حصة الشحن لا تُضاف؛
  الخصم على مستوى الفاتورة يُخصم حسب التناسب؛ الضريبة محسومة؛ والسعر بالمتوسط
  المتحرك للتكلفة وقت البيع) − تكلفة السطر.
  أي أن base_profit_line = (
      (line_total − alloc(line_discount)  [net of VAT for inclusive standard lines])
      × exchange_rate
  ) − qty × cost_price_base

  يُخصم من حصة الشريك دائمًا: الضريبة المخرَجة (لأنها ليست ربحًا) + الخصم
  (الذي يُنقص الإيراد) + الشحن (ليس إيراد المنتج). تُوزَّع النسب بالسطر.
  الفواتير السابقة تبقى بنسبتها القديمة — النسبة تُقرأ وقت الترحيل.

مستوى الشركة (Customer.partner_scope='company'):
  تُحسب النتيجة الصافية للفترة من الأستاذ (إيرادات − مصروفات، بما فيها ضريبة
  الدخل المُرحَّلة كمصروف — أي بعد الضريبة دون أي شهادات)، ثم تُوزَّع على
  الشركاء حسب ``partner_share``. يُخصم من حصة كل شريك في التوزيع:
  * المسحوبات المرتبطة به (قيود PartnerDraw بطرفه) في الفترة؛
  * مبيعات تمت له وغير مُسددة (balance_due محوَّل لعملة الأساس) في الفترة.
  الخسارة أيضًا تُوزَّع: صافي السالب يُحمَّل على الشركاء بنسبة حصتهم.

شريك ذو دورين (منتج + شركة): يحصل على الحصتين معًا — حصة المنتج تُرحَّل فورًا
مع كل فاتورة (مصروف 6910 يُخفض ربح الشركة)، وحصة الشركة تُوزَّع دوريًا على
صافي النتيجة بعد احتساب كل المصروفات بما فيها حصص المنتج المدفوعة. لا ازدواج
— كل حساب له أساس مستقل.

الذرّية: كل التوزيعات تُرحَّل داخل معاملة المستند (create_sale / create_return /
post_partner_distributions) — لا يُترك قيد إلا ومطروح به رصيد كامل.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from extensions import db
from models import GLJournalEntry, GLJournalLine
from services.account_resolution import AccountResolver, AccountRole

MONEY_Q = Decimal("0.001")
ZERO = Decimal("0")


def _q3(value):
    return Decimal(str(value or 0)).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def _num(value, default=ZERO):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(str(default))


def _subtotal(sale):
    subtotal = _num(getattr(sale, "subtotal", 0))
    if subtotal > ZERO:
        return subtotal
    total = ZERO
    for line in getattr(sale, "lines", []) or []:
        total += _num(getattr(line, "line_total", 0))
    return total


def _invoice_treatment(sale):
    return (getattr(sale, "tax_treatment", None) or "standard").strip().lower()


def _line_treatment(sale, line):
    invoice_treatment = _invoice_treatment(sale)
    if invoice_treatment in ("zero", "exempt"):
        return invoice_treatment
    return (getattr(line, "tax_treatment", None) or "standard").strip().lower()


def compute_line_profit(line, sale=None):
    """صافي ربح السطر بعملة الأساس — قبل نسب الشركاء على المنتج.

    الضريبة (إن كانت شاملة على سطر قياسي) محسومة من القاعدة، والخصم على
    مستوى الفاتورة يُوزَّع بنسبة قيمة السطر، والشحن لا يُضاف (ليس إيراد المنتج).
    النتيجة قد تكون سالبة (خسارة) — تُوزَّع كما هي.
    """
    if sale is None:
        sale = getattr(line, "sale", None)
    qty = _num(getattr(line, "quantity", 0))
    line_total = _num(getattr(line, "line_total", 0))
    cost_price = _num(getattr(line, "cost_price", 0))
    if qty <= ZERO or line_total <= ZERO:
        return ZERO.quantize(MONEY_Q)

    subtotal = _subtotal(sale) if sale is not None else line_total
    alloc_factor = (line_total / subtotal) if subtotal > ZERO else ZERO
    allocated_discount = ZERO
    if sale is not None:
        allocated_discount = _num(getattr(sale, "discount_amount", 0)) * alloc_factor

    base_txn = line_total - allocated_discount

    if sale is not None and bool(getattr(sale, "tax_inclusive", False)):
        rate = _num(getattr(sale, "tax_rate", 0))
        if rate > ZERO and _line_treatment(sale, line) == "standard":
            divisor = Decimal("1") + rate / Decimal("100")
            base_txn = base_txn / divisor

    rate = (
        _num(getattr(sale, "exchange_rate", 1), Decimal("1"))
        if sale is not None
        else Decimal("1")
    )
    if rate <= ZERO:
        rate = Decimal("1")
    base_rev = base_txn * rate
    return _q3(base_rev - qty * cost_price)


def compute_partner_shares(sale, factor_map=None):
    """{partner_id: signed share in base currency} للشركاء على المنتجات.

    ``factor_map``: اختياريًا {sale_line_id: Decimal multiplier (0..1)} — للمرتجعات.
    القيمة تعتمد حصة الشريك بالسطر's profit (لا نسبة ممّا تم تقسيطه).
    """
    from models import ProductPartner

    shares = {}
    lines = list(getattr(sale, "lines", []) or [])
    product_ids = {line.product_id for line in lines}
    if not product_ids:
        return {}

    partner_links = ProductPartner.query.filter(
        ProductPartner.product_id.in_(product_ids)
    ).all()
    partners_map = {}
    for pp in partner_links:
        partners_map.setdefault(pp.product_id, []).append(pp)

    for line in lines:
        profit = compute_line_profit(line, sale)
        if profit == ZERO:
            continue
        factor = Decimal("1")
        if factor_map is not None:
            factor = _num(factor_map.get(line.id), ZERO)
            if factor == ZERO:
                continue
        for pp in partners_map.get(line.product_id, []):
            pct = _num(pp.percentage)
            amount = _q3(profit * factor * pct / Decimal("100"))
            if amount == ZERO:
                continue
            shares[pp.partner_customer_id] = _q3(
                shares.get(pp.partner_customer_id, ZERO) + amount
            )

    return shares


def _resolve_role(role, tenant_id=None):
    """دور → كود حساب فعّال للمستأجر."""
    return AccountResolver.resolve(role, tenant_id=tenant_id)


def _share_lines(shares, *, sign, tenant_id=None):
    """بناء سطور القيد من {partner_id: signed amount}.

    sign=+1: ترحيل حصص جديدة (ربح → Dr المصروف/Cr الجاري؛ خسارة معكوسه)
    sign=-1: عكس الترحيل (يُسحب اتجاه كل سطر)
    """
    lines = []
    for partner_id, raw in sorted(shares.items()):
        amount = _q3(raw) * (Decimal("1") if sign >= 0 else Decimal("-1"))
        if amount == ZERO:
            continue
        if amount > ZERO:
            expense_side, current_side = "debit", "credit"
        else:
            expense_side, current_side = "credit", "debit"
        size = abs(amount)
        lines.append(
            {
                "account": _resolve_role(AccountRole.PARTNER_SHARE_EXPENSE, tenant_id),
                "description": "حصة الشريك في ربح الفاتورة",
                "party_id": partner_id,
                expense_side: size,
            }
        )
        lines.append(
            {
                "account": _resolve_role(AccountRole.PARTNERS_CURRENT, tenant_id),
                "description": "حصة الشريك في ربح الفاتورة",
                "party_id": partner_id,
                current_side: size,
            }
        )
    return lines


def post_partner_shares_for_sale(sale):
    """قيد حصص شركاء المنتج فورًا مع الفاتورة — داخل نفس المعاملة (قبل commit)."""
    from services.currency_service import CurrencyService
    from services.gl_service import GLService

    shares = compute_partner_shares(sale)
    if not shares:
        return None

    tid = getattr(sale, "tenant_id", None)
    lines = _share_lines(shares, sign=+1, tenant_id=tid)
    lines = [ln for ln in lines if (ln.get("debit") or ln.get("credit"))]
    if not lines:
        return None

    return GLService.post_entry(
        lines,
        description=f"Partner profit shares for Sale {sale.sale_number}",
        reference_type="Sale",
        reference_id=sale.id,
        currency=CurrencyService.get_base_currency(),
        exchange_rate=Decimal("1"),
    )


def post_partner_shares_for_return(product_return, sale=None):
    """عكس تناسبي لحصص شركاء المنتج مع كل مردود.

    يُنادى قبل commit لكل ProductReturn — يعكس نصيب ما رجع من الأسطر فقط
    (الكمية المرتجعة / الكمية المباعة لكل سطر) بنفس قاعدة الحساب والنسب.
    """
    from models import ProductReturnLine
    from services.currency_service import CurrencyService
    from services.gl_service import GLService

    if sale is None:
        sale = product_return.sale
    if sale is None:
        from models import Sale

        sale = Sale.query.get(product_return.sale_id)

    return_lines = getattr(product_return, "lines", None)
    if return_lines is None:
        from models import ProductReturnLine

        return_lines = ProductReturnLine.query.filter_by(
            return_id=product_return.id
        ).all()
    if not return_lines:
        return None

    sale_lines_by_id = {ln.id: ln for ln in getattr(sale, "lines", []) or []}
    factor_map = {}
    for rl in return_lines:
        sl = sale_lines_by_id.get(rl.sale_line_id)
        if sl is None:
            continue
        sold_qty = _num(sl.quantity)
        if sold_qty <= ZERO:
            continue
        factor_map[sl.id] = _q3(_num(rl.quantity) / sold_qty)

    if not factor_map:
        return None

    shares = compute_partner_shares(sale, factor_map=factor_map)
    if not shares:
        return None

    tid = getattr(sale, "tenant_id", None)
    lines = _share_lines(shares, sign=-1, tenant_id=tid)
    lines = [ln for ln in lines if (ln.get("debit") or ln.get("credit"))]
    if not lines:
        return None

    return GLService.post_entry(
        lines,
        description=f"Reverse partner profit shares for Return {product_return.return_number}",
        reference_type="ProductReturn",
        reference_id=product_return.id,
        currency=CurrencyService.get_base_currency(),
        exchange_rate=Decimal("1"),
    )


def compute_net_income(period_from=None, period_to=None):
    """النتيجة الدفترية للفترة (إيرادات − مصروفات، بعد ضريبة الدخل إن رُحِّلت).

    القيمة سالبة = خسارة الفترة. تُرحَّل على الشركاء بعلامتها.
    """
    from sqlalchemy import func
    from models import GLAccount, GLJournalEntry as _Entry

    revenue_q = (
        db.session.query(
            func.coalesce(func.sum(GLJournalLine.credit - GLJournalLine.debit), 0)
        )
        .join(_Entry, _Entry.id == GLJournalLine.entry_id)
        .join(GLAccount, GLAccount.id == GLJournalLine.account_id)
        .filter(_Entry.is_posted.is_(True), GLAccount.type == "revenue")
    )
    expense_q = (
        db.session.query(
            func.coalesce(func.sum(GLJournalLine.debit - GLJournalLine.credit), 0)
        )
        .join(_Entry, _Entry.id == GLJournalLine.entry_id)
        .join(GLAccount, GLAccount.id == GLJournalLine.account_id)
        .filter(_Entry.is_posted.is_(True), GLAccount.type == "expense")
    )
    if period_from is not None:
        revenue_q = revenue_q.filter(_Entry.entry_date >= period_from)
        expense_q = expense_q.filter(_Entry.entry_date >= period_from)
    if period_to is not None:
        revenue_q = revenue_q.filter(_Entry.entry_date <= period_to)
        expense_q = expense_q.filter(_Entry.entry_date <= period_to)

    revenue = _num(revenue_q.scalar())
    expenses = _num(expense_q.scalar())
    return _q3(revenue - expenses)


def _draws_for_partner(partner_id, period_from=None, period_to=None):
    """مسحوبات الشريك — أي مدين على جاري الشريك/المالك بطرفه في الفترة.

    تُحتسب القيود الموسومة بطرف الشريك على الحسابات الجارية (3300/3350) —
    يشمل ذلك المسحوبات اليدوية من واجهة القيد اليدوي (post_partner_draw
    أو قيد مباشر بأي طريقة)، ويستثني القيود المُولَّدة تلقائيًا (عكسات البيع/
    المرتجع/توزيع الخسارة/توزيع الأرباح) حتى لا تُحسب مرتين.
    """
    from sqlalchemy import func, or_
    from models import GLAccount, GLJournalEntry as _Entry

    q = (
        db.session.query(func.coalesce(func.sum(GLJournalLine.debit), 0))
        .join(_Entry, _Entry.id == GLJournalLine.entry_id)
        .join(GLAccount, GLAccount.id == GLJournalLine.account_id)
        .filter(
            _Entry.is_posted.is_(True),
            _Entry.is_reversed.is_(False),
            GLAccount.code.in_(("3300", "3350")),
            GLJournalLine.party_id == partner_id,
            or_(
                _Entry.reference_type.is_(None),
                _Entry.reference_type.notin_(
                    ("Sale", "ProductReturn", "PartnerDistribution")
                ),
            ),
        )
    )
    if period_from is not None:
        q = q.filter(_Entry.entry_date >= period_from)
    if period_to is not None:
        q = q.filter(_Entry.entry_date <= period_to)
    return _q3(q.scalar())


def _sales_to_partner(partner_id, period_from=None, period_to=None):
    """مبيعات الشركة للشريك **غير المسددة** في الفترة — بعملة الأساس.

    يُوزَّع دين العميل حتمًا من حصته (المبيعات لهتُخصم من استحقاقه) — لكن
    الفاتورة المسددة لا تأثير لها إطلاقًا: دفع ثمنها بالكامل. لذلك يُؤخذ
    ``balance_due × exchange_rate`` فقط.
    """
    from sqlalchemy import func
    from models import Sale

    q = db.session.query(
        func.coalesce(
            func.sum(Sale.balance_due * func.coalesce(Sale.exchange_rate, 1)), 0
        )
    ).filter(Sale.customer_id == partner_id, Sale.status != "cancelled")
    if period_from is not None:
        q = q.filter(Sale.sale_date >= period_from)
    if period_to is not None:
        q = q.filter(Sale.sale_date <= period_to)
    return _q3(q.scalar())


def _product_shares_in_period(partner_id, period_from=None, period_to=None):
    """حصص الشريك المتراكمة من المنتجات في الفترة (صافي Dr−Cr على 6910 بطرفه).

    معلومة فقط — لا تُخصم من توزيع الشركة (كل أساس مستقل)؛ تُعرض لإظهار
    إجمالي استحقاق الشريك صاحب الدورين في المعاينة.
    """
    from sqlalchemy import func
    from models import GLAccount, GLJournalEntry as _Entry

    q = (
        db.session.query(
            func.coalesce(func.sum(GLJournalLine.debit - GLJournalLine.credit), 0)
        )
        .join(_Entry, _Entry.id == GLJournalLine.entry_id)
        .join(GLAccount, GLAccount.id == GLJournalLine.account_id)
        .filter(
            _Entry.is_posted.is_(True),
            GLAccount.code == "6910",
            GLJournalLine.party_id == partner_id,
        )
    )
    if period_from is not None:
        q = q.filter(_Entry.entry_date >= period_from)
    if period_to is not None:
        q = q.filter(_Entry.entry_date <= period_to)
    return _q3(q.scalar())


def preview_partner_distributions(period_from=None, period_to=None, tenant_id=None):
    """معاينة بدون ترحيل — للربح والخسارة معًا."""
    from models import Customer

    period_from = _to_date(period_from)
    period_to = _to_date(period_to)
    net = compute_net_income(period_from, period_to)

    query = Customer.query.filter_by(partner_scope="company", is_active=True).filter(
        Customer.partner_share.isnot(None)
    )
    if tenant_id is not None:
        query = query.filter(Customer.tenant_id == tenant_id)
    partners = query.order_by(Customer.partner_share.desc(), Customer.id.asc()).all()

    # استعلامات مجمعة (N+1 fix) — استعلام واحد لكل aggregate
    product_accrual = _product_shares_bulk(
        [p.id for p in partners], period_from, period_to
    )
    draws_bulk = _draws_for_partners_bulk(
        [p.id for p in partners], period_from, period_to
    )
    sales_bulk = _sales_to_partners_bulk(
        [p.id for p in partners], period_from, period_to
    )

    total_pct = sum(_num(p.partner_share) for p in partners)
    residual_pct = max(Decimal("100") - total_pct, ZERO)
    rows = []
    for partner in partners:
        pct = _num(partner.partner_share)
        share = _q3(net * pct / Decimal("100"))
        draws = draws_bulk.get(partner.id, ZERO)
        sales_to_him = sales_bulk.get(partner.id, ZERO)
        if share >= ZERO:
            deductions = _q3(draws + sales_to_him)
            payout = max(_q3(share - deductions), ZERO)
        else:
            deductions = ZERO
            payout = share  # الخسارة تُحمَّل كاملة على الشريك
        products = product_accrual.get(partner.id, ZERO)
        rows.append(
            {
                "partner_id": partner.id,
                "partner_name": partner.name,
                "partner_share_pct": pct,
                "share_amount": share,
                "draws_deducted": draws,
                "sales_to_partner_deducted": sales_to_him,
                "net_payout": payout,
                "product_shares_in_period": products,
                "total_entitlement": _q3(payout + products),
            }
        )
    rows.append(
        {
            "partner_id": None,
            "partner_name": "الملاك المتبقون",
            "partner_share_pct": residual_pct,
            "share_amount": _q3(net * residual_pct / Decimal("100")),
            "draws_deducted": ZERO,
            "sales_to_partner_deducted": ZERO,
            "net_payout": _q3(net * residual_pct / Decimal("100")),
            "product_shares_in_period": ZERO.quantize(MONEY_Q),
            "total_entitlement": _q3(net * residual_pct / Decimal("100")),
        }
    )
    return rows


def _to_date(v):
    if v is None:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return None


def _marker_window(marker):
    """تحليل علامة التوزيع 'partner-distribution:FROM:TO:TID' إلى (from, to)."""
    parts = (marker or "").split(":")
    if len(parts) != 4:
        return None
    raw_from, raw_to = parts[1], parts[2]
    d_from = date.fromisoformat(raw_from) if raw_from not in ("-", "") else date.min
    d_to = date.fromisoformat(raw_to) if raw_to not in ("-", "") else date.max
    return d_from, d_to


def _guard_against_overlapping_periods(period_from, period_to, tid):
    """يرفض توزيع أي فترة تتقاطع مع توزيع سابق مُرحَّل لنفس التينانت."""

    req_from = period_from or date.min
    req_to = period_to or date.max
    rows = (
        GLJournalEntry.query.filter_by(
            reference_type="PartnerDistribution", is_posted=True, is_reversed=False
        )
        .filter(GLJournalEntry.notes.like("partner-distribution:%"))
        .all()
    )
    for row in rows:
        info = _marker_window(row.notes)
        if info is None:
            continue
        w_from, w_to = info
        # نطاق التينانت في العلامة — يستبعد توزعات تينانتات أخرى إن وُجدت
        tid_part = (row.notes or "").split(":")[-1]
        if (tid is not None or tid_part != "platform") and tid_part != str(
            tid or "platform"
        ):
            continue
        if not (w_to < req_from or req_to < w_from):
            raise ValueError(
                f"يوجد توزيع سابق متداخل لنفس التينانت على الفترة "
                f"{w_from} إلى {w_to} — لا يمكن توزيع {req_from}–{req_to} مرة أخرى "
                f"لأن الربح سيُدفع مرتين. حدد فترة لا تتقاطع أو اعكس القيد أولًا."
            )


def post_partner_distributions(
    period_from=None, period_to=None, tenant_id=None, force=False
):
    """التوزيع الدوري النهائي على شركات الشركاء — ربحًا كان أم خسارة.

    الربح: Cr لكل شريك (3350) بعد خصم مسحوباته والمبيعات له؛ Dr 3400 للجزء الموزَّع.
    الخسارة: Dr لكل شريك (3350) بحصته من الخسارة؛ Cr 3400.

    idempotent لنفس الفترة تمامًا: إعادة تنفيذ نفس الفترة تعيد ``None`` ولا
    تُرحّل قيدًا مكررًا (المعلومة تتبع القيد عبر ``notes``). أي فترة تتقاطع مع
    توزيع سابق مُرحَّل ترفع ``ValueError`` — الربح لا يُوزَّع مرتين.
    ``force=True`` يتخطى فحص التقاطع (للاستخدامات الإدارية المقصودة فقط).
    """
    from models import Customer, GLJournalLine  # noqa: F401
    from services.currency_service import CurrencyService
    from services.gl_service import GLService

    tid = tenant_id
    period_from = _to_date(period_from)
    period_to = _to_date(period_to)

    marker = (
        f"partner-distribution:"
        f"{period_from.isoformat() if period_from else '-'}:"
        f"{period_to.isoformat() if period_to else '-'}:{tid or 'platform'}"
    )
    existing = (
        GLJournalEntry.query.filter_by(
            reference_type="PartnerDistribution", is_posted=True, is_reversed=False
        )
        .filter(GLJournalEntry.notes == marker)
        .first()
    )
    if existing is not None:
        return None

    # حظر تداخل أي توزيعين لنفس التينانت — الربح القديم لا يُوزَّع مرتين.
    if not force:
        _guard_against_overlapping_periods(period_from, period_to, tid)

    net = compute_net_income(period_from, period_to)
    if net == ZERO:
        return None

    query = Customer.query.filter_by(partner_scope="company", is_active=True).filter(
        Customer.partner_share.isnot(None)
    )
    if tid is not None:
        query = query.filter(Customer.tenant_id == tid)
    partners = query.order_by(Customer.partner_share.desc(), Customer.id.asc()).all()

    # 🔒 Concurrency: lock each partner's customer row so two concurrent
    # distributions cannot both read the same draws/sales/balance.
    for p in partners:
        Customer.query.filter_by(id=p.id).with_for_update().first()

    # استعلامات مجمعة (N+1 fix)
    draws_bulk = _draws_for_partners_bulk(
        [p.id for p in partners], period_from, period_to
    )
    sales_bulk = _sales_to_partners_bulk(
        [p.id for p in partners], period_from, period_to
    )

    total_pct = sum(_num(p.partner_share) for p in partners)
    if total_pct > Decimal("100"):
        raise ValueError("مجموع نسب الشركاء يتجاوز 100%")
    residual_pct = Decimal("100") - total_pct

    partners_account = _resolve_role(AccountRole.PARTNERS_CURRENT, tid)
    lines = []
    distributed = ZERO
    distribute_loss = net < ZERO

    for partner in partners:
        pct = _num(partner.partner_share)
        share = _q3(net * pct / Decimal("100"))
        if share >= ZERO:
            draws = draws_bulk.get(partner.id, ZERO)
            sales_to_him = sales_bulk.get(partner.id, ZERO)
            payout = max(_q3(share - draws - sales_to_him), ZERO)
        else:
            payout = share  # تحمل الخسارة
        if payout == ZERO:
            continue
        if not distribute_loss:
            lines.append(
                {
                    "account": partners_account,
                    "credit": payout,
                    "description": (
                        f"توزيع أرباح الشركة للشريك {partner.name} "
                        f"({partner.partner_share}%)"
                    ),
                    "party_id": partner.id,
                }
            )
        else:
            lines.append(
                {
                    "account": partners_account,
                    "debit": -payout,
                    "description": (
                        f"تحمل خسائر الشركة من الشريك {partner.name} "
                        f"({partner.partner_share}%)"
                    ),
                    "party_id": partner.id,
                }
            )
        distributed = _q3(distributed + abs(payout))

    if residual_pct > ZERO:
        residual = _q3(net * residual_pct / Decimal("100"))
        if residual != ZERO:
            if not distribute_loss:
                lines.append(
                    {
                        "account": partners_account,
                        "credit": residual,
                        "description": f"توزيع أرباح للملاك المتبقين ({residual_pct}%)",
                    }
                )
            else:
                lines.append(
                    {
                        "account": partners_account,
                        "debit": -residual,
                        "description": f"تحمل خسائر الملاك المتبقين ({residual_pct}%)",
                    }
                )
            distributed = _q3(distributed + abs(residual))

    if not lines:
        return None

    resolved_profit_account = _resolve_role(AccountRole.CURRENT_YEAR_PROFIT, tid)
    if not distribute_loss:
        lines.insert(
            0,
            {
                "account": resolved_profit_account,
                "debit": distributed,
                "description": (
                    f"توزيع أرباح الشركة للفترة "
                    f"{period_from or 'البداية'}–{period_to or 'اليوم'}"
                ),
            },
        )
    else:
        lines.insert(
            0,
            {
                "account": resolved_profit_account,
                "credit": distributed,
                "description": (
                    f"تحمل خسائر الشركة للفترة "
                    f"{period_from or 'البداية'}–{period_to or 'اليوم'}"
                ),
            },
        )

    base_currency = CurrencyService.get_base_currency()
    return GLService.post_entry(
        lines,
        description=(
            f"Company profit distribution {period_from or ''} – {period_to or ''}"
            if not distribute_loss
            else f"Company loss allocation {period_from or ''} – {period_to or ''}"
        ),
        reference_type="PartnerDistribution",
        reference_id=None,
        currency=base_currency,
        exchange_rate=Decimal("1"),
        entry_type="closing",
        notes=marker,
    )


def post_partner_draw(
    partner_customer_id,
    amount,
    *,
    credit_account_role=AccountRole.CASH,
    description=None,
    currency=None,
    exchange_rate=Decimal("1"),
):
    """تسجيل مسحوبات الشريك (توصيلها يدويًا بطرفه) — تُخصم تلقائيًا من توزيعه.

    Dr 3350 (جاري الشريك — طرف بطرفه) / Cr النقدية (أو البنك).
    """
    from models import Customer
    from services.currency_service import CurrencyService
    from services.gl_service import GLService

    amount = _q3(amount)
    if amount <= ZERO:
        raise ValueError("مبلغ المسحوبات يجب أن يكون أكبر من صفر")

    partner = Customer.query.get(int(partner_customer_id))
    if partner is None or not partner.is_active:
        raise ValueError("الشريك غير موجود")

    base_currency = currency or CurrencyService.get_base_currency()
    rate = _q3(Decimal(str(exchange_rate or Decimal("1"))))
    if rate <= ZERO:
        rate = Decimal("1")

    entry = GLService.post_entry(
        [
            {
                "account": AccountResolver.resolve(
                    AccountRole.PARTNERS_CURRENT,
                    tenant_id=getattr(partner, "tenant_id", None),
                ),
                "debit": amount,
                "description": description or f"مسحوبات الشريك {partner.name}",
                "party_id": partner.id,
            },
            {
                "account": AccountResolver.resolve(
                    credit_account_role, tenant_id=getattr(partner, "tenant_id", None)
                ),
                "credit": amount,
                "description": description or f"مسحوبات الشريك {partner.name}",
                "party_id": partner.id,
            },
        ],
        description=description or f"مسحوبات الشريك {partner.name}",
        reference_type="PartnerDraw",
        reference_id=partner.id,
        currency=base_currency,
        exchange_rate=rate,
    )
    return entry


def main(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Partner profit-sharing tools")
    parser.add_argument("--from", dest="from_", default=None)
    parser.add_argument("--to", dest="to", default=None)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--distribute", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="يتخطى فحص تداخل الفترات (استخدام إداري مقصود فقط)",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    if args.preview:
        rows = preview_partner_distributions(args.from_, args.to)
        for r in rows:
            print(
                f"{r['partner_name']}: حصة {r['partner_share_pct']}% = {r['share_amount']}"
                f" — مسحوبات {r['draws_deducted']} — مبيعات له {r['sales_to_partner_deducted']}"
                f" — الصافي الشركة {r['net_payout']}"
                f" — حصص المنتج في الفترة {r.get('product_shares_in_period', 0)}"
                f" — الإجمالي {r.get('total_entitlement', r['net_payout'])}"
            )
    elif args.distribute:
        entry = post_partner_distributions(args.from_, args.to, force=args.force)
        print(
            f"Distributed: {entry.entry_number}" if entry else "Nothing to distribute."
        )


if __name__ == "__main__":
    main()


def _product_shares_bulk(partner_ids, period_from=None, period_to=None):
    """حصص المنتجات متراكمة في الفترة — dict {partner_id: Decimal} (استعلام واحد).

    يحل محل N استعلام فردي (واحد لكل شريك) — يُستخدم في المعاينة وصفحة المالك.
    """
    from sqlalchemy import func
    from models import GLAccount, GLJournalEntry as _Entry

    if not partner_ids:
        return {}
    q = (
        db.session.query(
            GLJournalLine.party_id,
            func.coalesce(func.sum(GLJournalLine.debit - GLJournalLine.credit), 0),
        )
        .join(_Entry, _Entry.id == GLJournalLine.entry_id)
        .join(GLAccount, GLAccount.id == GLJournalLine.account_id)
        .filter(
            _Entry.is_posted.is_(True),
            GLAccount.code == "6910",
            GLJournalLine.party_id.in_(list(partner_ids)),
        )
    )
    if period_from is not None:
        q = q.filter(_Entry.entry_date >= period_from)
    if period_to is not None:
        q = q.filter(_Entry.entry_date <= period_to)
    q = q.group_by(GLJournalLine.party_id)
    return {pid: _q3(total) for pid, total in q.all()}


def _draws_for_partners_bulk(partner_ids, period_from=None, period_to=None):
    """مسحوبات كل شريك في استعلام واحد (N+1 fix)."""
    from sqlalchemy import func
    from models import GLAccount, GLJournalEntry as _Entry

    if not partner_ids:
        return {}
    from sqlalchemy import or_

    q = (
        db.session.query(
            GLJournalLine.party_id, func.coalesce(func.sum(GLJournalLine.debit), 0)
        )
        .join(_Entry, _Entry.id == GLJournalLine.entry_id)
        .join(GLAccount, GLAccount.id == GLJournalLine.account_id)
        .filter(
            _Entry.is_posted.is_(True),
            _Entry.is_reversed.is_(False),
            GLAccount.code.in_(("3300", "3350")),
            GLJournalLine.party_id.in_(list(partner_ids)),
            or_(
                _Entry.reference_type.is_(None),
                _Entry.reference_type.notin_(
                    ("Sale", "ProductReturn", "PartnerDistribution")
                ),
            ),
        )
    )
    if period_from is not None:
        q = q.filter(_Entry.entry_date >= period_from)
    if period_to is not None:
        q = q.filter(_Entry.entry_date <= period_to)
    q = q.group_by(GLJournalLine.party_id)
    return {pid: _q3(total) for pid, total in q.all()}


def _sales_to_partners_bulk(partner_ids, period_from=None, period_to=None):
    """مبيعات غير مسددة لكل شريك في استعلام واحد (N+1 fix)."""
    from sqlalchemy import func
    from models import Sale

    if not partner_ids:
        return {}
    q = db.session.query(
        Sale.customer_id,
        func.coalesce(
            func.sum(Sale.balance_due * func.coalesce(Sale.exchange_rate, 1)), 0
        ),
    ).filter(Sale.customer_id.in_(list(partner_ids)), Sale.status != "cancelled")
    if period_from is not None:
        q = q.filter(Sale.sale_date >= period_from)
    if period_to is not None:
        q = q.filter(Sale.sale_date <= period_to)
    q = q.group_by(Sale.customer_id)
    return {pid: _q3(total) for pid, total in q.all()}
