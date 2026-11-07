"""Shared sales tax arithmetic.

Supports both the invoice-level API (single treatment) and the per-line API
needed for mixed invoices. Amounts are in transaction currency.
"""
from decimal import Decimal, ROUND_HALF_UP

TREATMENTS = ('standard', 'zero', 'exempt')
ZERO_TREATMENTS = ('zero', 'exempt')

MONEY_Q = Decimal('0.001')
TAX_Q = Decimal('0.01')


def _num(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def _treatment(value):
    value = (value or 'standard').strip().lower()
    if value not in TREATMENTS:
        raise ValueError('invalid tax treatment')
    return value


def split_lines(lines):
    """Sum line totals by treatment bucket.

    lines: iterable of dicts with keys ``line_total`` and ``tax_treatment``.
    Returns (standard, zero, exempt) Decimals.
    """
    buckets = {'standard': Decimal('0'), 'zero': Decimal('0'), 'exempt': Decimal('0')}
    for line in lines:
        treatment = _treatment(line.get('tax_treatment'))
        buckets[treatment] += _num(line.get('line_total'))
    return (buckets['standard'], buckets['zero'], buckets['exempt'])


def sale_tax_totals_mixed(lines, discount, shipping, rate, inclusive,
                          invoice_treatment='standard'):
    """Per-line buckets.

    ``lines`` iterable of dicts with ``line_total`` (net pre-tax for exclusive
    prices, gross for inclusive) and ``tax_treatment``. Invoice-level
    treatment (zero/exempt) overrides every line.

    Returns (tax, total, standard_net_base, zero_net, exempt_net) where the
    net figures exclude VAT.
    """
    discount, shipping, rate = (_num(v) for v in (discount, shipping, rate))
    invoice_treatment = _treatment(invoice_treatment)

    std_sum, zero_sum, exempt_sum = split_lines(lines)
    subtotal = std_sum + zero_sum + exempt_sum
    if invoice_treatment in ZERO_TREATMENTS:
        # المستند كله صفري أو معفى — ائتلاف كامل إلى سلة تلك المعاملة.
        allocable = (subtotal - discount + shipping).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)
        tax = Decimal('0')
        if invoice_treatment == 'zero':
            return tax, allocable, Decimal('0'), allocable, Decimal('0')
        return tax, allocable, Decimal('0'), Decimal('0'), allocable
    if subtotal == 0:
        tax = Decimal('0')
        return tax, Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')

    # Shipping and global discount are spread over lines in proportion to
    # their value; zero/exempt lines take no VAT but do take their share.
    std_share = std_sum / subtotal
    zero_share = zero_sum / subtotal
    exempt_share = exempt_sum / subtotal
    std_base = (std_sum - discount * std_share
                + shipping * std_share).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
    zero_base = (zero_sum - discount * zero_share
                 + shipping * zero_share).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
    exempt_base = (exempt_sum - discount * exempt_share
                   + shipping * exempt_share).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

    if std_base < 0:
        std_base = Decimal('0')

    if inclusive:
        divisor = Decimal('1') + rate / Decimal('100')
        net_std = (std_base / divisor).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        tax = (std_base - net_std).quantize(TAX_Q, rounding=ROUND_HALF_UP)
        total = (subtotal - discount + shipping).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        net_zero = zero_base
        net_exempt = exempt_base
    else:
        tax = (std_base * rate / Decimal('100')).quantize(
            TAX_Q, rounding=ROUND_HALF_UP)
        total = (subtotal - discount + shipping + tax).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)
        net_std = std_base
        net_zero = zero_base
        net_exempt = exempt_base
    return tax, total, net_std, net_zero, net_exempt


def return_tax_parts(returned_lines, all_sale_lines, subtotal_all,
                     discount, shipping, rate, inclusive, invoice_treatment='standard'):
    """Per returned line bucket split.

    ``returned_lines``: dicts {line_total} for the lines being returned.
    ``all_sale_lines`` / ``subtotal_all`` give the denominator for the
    shipping/discount allocation. Returns (tax, net_std, zero_base, exempt_base).
    """
    discount, shipping, rate = (_num(v) for v in (discount, shipping, rate))
    invoice_treatment = _treatment(invoice_treatment)

    std = zero = exempt = Decimal('0')
    for line in returned_lines:
        if invoice_treatment in ZERO_TREATMENTS:
            treat = invoice_treatment
        else:
            treat = _treatment(line.get('tax_treatment'))
        amount = _num(line.get('line_total'))
        if treat == 'zero':
            zero += amount
        elif treat == 'exempt':
            exempt += amount
        else:
            std += amount
    subtotal_all = _num(subtotal_all)
    if subtotal_all <= 0:
        for line in (all_sale_lines or []):
            try:
                subtotal_all += _num(line.line_total)
            except AttributeError:
                subtotal_all += _num((line or {}).get('line_total'))
    if subtotal_all > 0:
        std_share = std / subtotal_all
        zero_share = zero / subtotal_all
        exempt_share = exempt / subtotal_all
    else:
        std_share = zero_share = exempt_share = Decimal('0')
    std_base = (std - discount * std_share + shipping * std_share).quantize(
        MONEY_Q, rounding=ROUND_HALF_UP)
    zero_base = (zero - discount * zero_share + shipping * zero_share).quantize(
        MONEY_Q, rounding=ROUND_HALF_UP)
    exempt_base = (exempt - discount * exempt_share + shipping * exempt_share).quantize(
        MONEY_Q, rounding=ROUND_HALF_UP)

    if invoice_treatment in ZERO_TREATMENTS or rate <= 0 or std_base <= 0:
        return Decimal('0'), std_base, zero_base, exempt_base
    if inclusive:
        divisor = Decimal('1') + rate / Decimal('100')
        net_std = (std_base / divisor).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        # نفس منزلة net حتى لا ينكسر net + tax == gross
        tax = (std_base - net_std).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        return tax, net_std, zero_base, exempt_base
    tax = (std_base * rate / Decimal('100')).quantize(
        TAX_Q, rounding=ROUND_HALF_UP)
    return tax, std_base, zero_base, exempt_base
