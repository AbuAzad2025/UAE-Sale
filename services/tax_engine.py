"""Centralised Tax/VAT engine (Agent 4).

Pure functions for VAT math plus thin helpers for GL liability routing.

Policy (documented, asserted in tests/unit/test_tax_engine.py):
    * Money is ``Decimal`` everywhere; inputs are coerced via ``Decimal(str(x))``
      at the boundary. Float arithmetic on amounts is banned.
    * Rounding mode defaults to ``ROUND_HALF_UP`` with a default quantum of
      ``Decimal('0.001')`` (the ledger stores Numeric(15, 3)).
    * Prices are treated as tax-EXCLUSIVE unless ``price_includes_tax=True``,
      in which case the given amount is the GROSS figure and tax is the
      residual ``gross - net`` where ``net = gross / (1 + rate/100)``.
    * Invoice accumulation policy: PER-LINE rounding first, then sum.
      ``Σ(line.tax)`` may legitimately differ from ``tax_on_invoice_total``
      by a few quanta when many lines each lose/gain half-a-quantum;
      consumers must reconcile to the per-line sum (see tests).
    * ``split_gross`` decomposes a gross figure into integer minor units
      (exact rational arithmetic) so that ``net + tax == gross`` EXACTLY,
      with both components on the currency grid.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from fractions import Fraction

DEFAULT_QUANTUM = Decimal('0.001')
HUNDRED = Decimal('100')
ONE = Decimal('1')

# Fallback literal CoA codes (become obsolete once Agent 1's resolver ships;
# they mirror today's gl_service.ensure_core_accounts() chart).
_ROLE_FALLBACKS = {
    'output_vat': 'TAX_PAYABLE',
    'sales_returns': 'SALES_RETURNS',
    'sales_revenue': 'SALES_REVENUE',
    'ar_control': 'AR_CONTROL',
    'inventory': 'INVENTORY',
    'cogs': 'COGS',
}
_CODE_FALLBACKS = {
    'output_vat': '2130',
    'sales_returns': '4100',
    'sales_revenue': '4100',
    'ar_control': '1130',
    'inventory': '1140',
    'cogs': '5100',
}


def to_decimal(value):
    """Coerce boundary input to Decimal (never float arithmetic)."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f'Cannot interpret {value!r} as a decimal amount') from exc


def _validated(amount, rate, quantum):
    amount_d = to_decimal(amount)
    rate_d = to_decimal(rate)
    quantum_d = to_decimal(quantum)
    if amount_d < 0:
        raise ValueError(f'Tax base must be non-negative, got {amount_d}')
    if rate_d < 0:
        raise ValueError(f'Tax rate must be non-negative, got {rate_d}')
    if quantum_d <= 0:
        raise ValueError(f'Rounding quantum must be positive, got {quantum_d}')
    return amount_d, rate_d, quantum_d


class TaxEngine:
    """Single source of truth for indirect-tax arithmetic."""

    # ------------------------------------------------------------------ #
    # Pure computations
    # ------------------------------------------------------------------ #
    @staticmethod
    def compute_line_tax(amount, rate, *, price_includes_tax=False,
                         rounding=ROUND_HALF_UP, quantum=DEFAULT_QUANTUM):
        """Compute {net, tax, gross} for one line.

        ``amount`` is the NET figure when ``price_includes_tax=False``
        (default, exclusive pricing) or the GROSS figure when True.

        Components always satisfy ``net + tax == gross`` exactly at the
        requested ``quantum``.
        """
        amount_d, rate_d, quantum_d = _validated(amount, rate, quantum)

        if price_includes_tax:
            divisor = ONE + rate_d / HUNDRED
            net = (amount_d / divisor).quantize(quantum_d, rounding=rounding)
            tax = (amount_d - net).quantize(quantum_d, rounding=rounding)
            gross = net + tax
            return {'net': net, 'tax': tax, 'gross': gross}

        net = amount_d.quantize(quantum_d, rounding=rounding)
        tax = (net * rate_d / HUNDRED).quantize(quantum_d, rounding=rounding)
        gross = net + tax
        return {'net': net, 'tax': tax, 'gross': gross}

    @staticmethod
    def compute_invoice(lines, *, rounding=ROUND_HALF_UP, quantum=DEFAULT_QUANTUM):
        """Compute an invoice breakdown from line specs.

        Each element of ``lines`` may be:
          * ``{'amount': x, 'rate': r[, 'price_includes_tax': bool]}``
          * ``{'net': x, 'rate': r}`` (shorthand, exclusive)
          * ``{'gross': x, 'rate': r}`` (shorthand, inclusive)
          * ``(amount, rate)`` tuple (exclusive)

        POLICY: every line is rounded independently (half-up at ``quantum``)
        and invoice totals are the SUM of rounded lines. This means
        ``total_tax`` can differ from recomputing tax once on the invoice
        total by a few quanta; that divergence is intentional and tested.
        """
        per_line = []
        total_net = Decimal('0')
        total_tax = Decimal('0')
        total_gross = Decimal('0')

        for index, spec in enumerate(lines):
            amount, rate, includes_tax = TaxEngine._normalise_line(spec, index)
            computed = TaxEngine.compute_line_tax(
                amount, rate,
                price_includes_tax=includes_tax,
                rounding=rounding, quantum=quantum,
            )
            per_line.append(computed)
            total_net += computed['net']
            total_tax += computed['tax']
            total_gross += computed['gross']

        quantum_d = to_decimal(quantum)
        return {
            'per_line': per_line,
            'total_net': total_net.quantize(quantum_d, rounding=rounding),
            'total_tax': total_tax.quantize(quantum_d, rounding=rounding),
            'total_gross': total_gross.quantize(quantum_d, rounding=rounding),
        }

    @staticmethod
    def split_gross(gross, rate, *, currency_digits=2):
        """Decompose a gross figure into net + tax exactly.

        Works in integer minor units (e.g. cents) using exact rational
        arithmetic, so ``net + tax == gross`` holds EXACTLY on the currency
        grid — safe for penny-perfect VAT returns and reversals.
        """
        gross_d, rate_d, _ = _validated(gross, rate, DEFAULT_QUANTUM)
        scale = Decimal(10) ** int(currency_digits)
        gross_units = int((gross_d * scale).to_integral_value(rounding=ROUND_HALF_UP))

        exact = Fraction(gross_units) * Fraction(str(rate_d)) / (
            100 + Fraction(str(rate_d))
        )
        numerator, denominator = exact.numerator, exact.denominator
        # Integer half-up division for a non-negative fraction.
        tax_units = (2 * numerator + denominator) // (2 * denominator)
        net_units = gross_units - tax_units

        unit = ONE.scaleb(-int(currency_digits))
        return {
            'net': Decimal(net_units) * unit,
            'tax': Decimal(tax_units) * unit,
            'gross': Decimal(gross_units) * unit,
        }

    # ------------------------------------------------------------------ #
    # Thin persistence / routing helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def liability_routing(tenant_id=None):
        """Resolve GL accounts for tax-related postings.

        Consumes Agent 1's central ``AccountResolver`` defensively: if the
        module is absent (parallel development) or resolution fails, falls
        back to today's literal chart codes.
        """
        routing = {}
        for key, role_name in _ROLE_FALLBACKS.items():
            routing[key] = TaxEngine._resolve_account(role_name, key, tenant_id)
        return routing

    @staticmethod
    def _resolve_account(role_name, fallback_key, tenant_id=None):
        fallback_code = _CODE_FALLBACKS[fallback_key]
        try:
            from services.account_resolution import AccountRole, AccountResolver
            try:
                role = AccountRole[role_name]
            except KeyError:
                role = AccountRole(role_name)
            resolved = AccountResolver.resolve(role, tenant_id=tenant_id)
            return str(resolved) if resolved else fallback_code
        except Exception:
            return fallback_code

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalise_line(spec, index):
        if isinstance(spec, dict):
            rate = spec.get('rate', 0)
            if 'amount' in spec:
                return spec['amount'], rate, bool(spec.get('price_includes_tax', False))
            if 'gross' in spec:
                return spec['gross'], rate, True
            if 'net' in spec:
                return spec['net'], rate, False
            raise ValueError(f'Invoice line {index}: missing amount/net/gross')
        if isinstance(spec, (tuple, list)) and len(spec) == 2:
            return spec[0], spec[1], False
        raise ValueError(f'Invoice line {index}: unsupported specification {spec!r}')


# ---------------------------------------------------------------------------
# Tenant/country layer (UAE-VAT tenant system).
# Core arithmetic above is the single source of truth; these helpers add
# country presets + inclusive flag + tenant resolution on top only.
# ---------------------------------------------------------------------------
COUNTRY_VAT = {
    'AE': Decimal('5.00'), 'SA': Decimal('15.00'), 'BH': Decimal('10.00'),
    'OM': Decimal('5.00'), 'KW': Decimal('5.00'), 'EG': Decimal('14.00'),
    'JO': Decimal('16.00'), 'TR': Decimal('20.00'), 'GB': Decimal('20.00'),
    'DE': Decimal('19.00'),
}
COUNTRY_LABEL_AR = {
    'AE': 'الإمارات', 'SA': 'السعودية', 'BH': 'البحرين', 'OM': 'عمان',
    'KW': 'الكويت', 'EG': 'مصر', 'JO': 'الأردن', 'TR': 'تركيا', 'GB': 'بريطانيا', 'DE': 'ألمانيا',
}


def country_rate(country_code):
    if not country_code:
        return None
    # أولوية للقاعدة المخزَّنة في قاعدة البيانات (قابل للتعديل من المالك)
    # ثم الاحتياطي الثابت فقط إذا غاب الجدول — وهو دائمًا ممكن التزويد
    try:
        from models.tax_ruleset import TaxRuleset
        row = TaxRuleset.query.filter_by(country_code=country_code.upper(), tenant_id=None, is_active=True).first()
        if row is not None and row.vat_rate is not None:
            return Decimal(str(row.vat_rate))
    except Exception:
        pass
    return COUNTRY_VAT.get(country_code.upper())


def resolve(tenant, explicit_rate=None, explicit_inclusive=None):
    """(rate, inclusive) for tenant - explicit wins per-invoice."""
    if tenant is None:
        return (explicit_rate if explicit_rate is not None else Decimal('0'),
                bool(explicit_inclusive) if explicit_inclusive is not None else False)
    if not getattr(tenant, 'enable_tax', True):
        return Decimal('0'), bool(explicit_inclusive) if explicit_inclusive is not None else False
    rate = explicit_rate if explicit_rate is not None else getattr(tenant, 'default_tax_rate', None)
    if rate is None:
        # احترم قاعدة الدولة المخزَّنة أولاً؛ ثم الاحتياطي الثابت
        try:
            from models.tax_ruleset import ruleset_for_tenant
            ruleset = ruleset_for_tenant(tenant)
            if ruleset is not None and ruleset.vat_rate is not None:
                rate = ruleset.vat_rate
        except Exception:
            rate = None
    if rate is None:
        rate = getattr(tenant, 'tax_country_rate', None)
    if rate is None:
        rate = country_rate(getattr(tenant, 'tax_country', None) or getattr(tenant, 'country', None)) or Decimal('0')
    inclusive = explicit_inclusive if explicit_inclusive is not None else bool(getattr(tenant, 'tax_inclusive', False))
    return Decimal(str(rate)), bool(inclusive)


def calc(net_subtotal, discount, shipping, rate, inclusive):
    """(tax, total) via TaxEngine arithmetic (authority stays there)."""
    net = to_decimal(net_subtotal) - to_decimal(discount) + to_decimal(shipping)
    result = TaxEngine.compute_line_tax(net, rate, price_includes_tax=bool(inclusive))
    return result['tax'], result['gross']
