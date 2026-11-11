"""Pure maintenance pricing primitive; not yet connected to posting or routes.

Amounts use three decimal places, like the existing document columns, and VAT
is rounded to two places per treatment/rate bucket, as in the sales tax engine.
Document discounts are applied to the entered price basis: net for exclusive
prices and gross for inclusive prices. This calculation is not a tax return,
invoice, GL posting, or a statement that the maintenance workflow is ready.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP, localcontext

from utils.errors import ValidationError


MONEY_QUANTUM = Decimal('0.001')
TAX_QUANTUM = Decimal('0.01')
PERCENT_QUANTUM = Decimal('0.01')
MAX_MONEY = Decimal('999999999999.999')  # NUMERIC(15, 3)
ZERO = Decimal('0')
ONE_HUNDRED = Decimal('100')


@dataclass(frozen=True)
class PriceLine:
    quantity: object
    unit_price: object
    tax_rate: object = ZERO
    tax_treatment: str = 'standard'
    discount_mode: str = 'percent'
    discount_percent: object = ZERO
    discount_value: object = ZERO


@dataclass(frozen=True)
class CalculatedLine:
    original_amount: Decimal
    line_discount: Decimal
    order_discount: Decimal
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    tax_rate: Decimal
    tax_treatment: str


@dataclass(frozen=True)
class PricingTotals:
    price_basis_subtotal: Decimal  # after line discounts, before order discount
    line_discount: Decimal
    order_discount: Decimal       # in the entered price basis, not necessarily net
    net_amount: Decimal           # after all discounts, excluding VAT
    tax_amount: Decimal
    total_amount: Decimal
    lines: tuple[CalculatedLine, ...]


def _number(value, label, quantum, maximum):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > maximum:
            raise ValueError
        if number.quantize(quantum) != number:
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f'{label} غير صالح أو يتجاوز الدقة المسموحة') from None
    return number


def _money(value):
    value = value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if value < 0 or value > MAX_MONEY:
        raise ValidationError('المبلغ يتجاوز الحدود المسموحة')
    return value


def _allocate(total, weights):
    """Allocate rounded units proportionally, using stable largest remainder."""
    if not weights:
        return []
    total = _money(total)
    if total == ZERO:
        return [ZERO.quantize(MONEY_QUANTUM)] * len(weights)
    weight_total = sum(weights, ZERO)
    if weight_total <= ZERO:
        raise ValidationError('لا يمكن توزيع المبلغ على بنود صفرية')
    units = int(total / MONEY_QUANTUM)
    shares = [Decimal(units) * weight / weight_total for weight in weights]
    floors = [int(share.to_integral_value(rounding=ROUND_DOWN)) for share in shares]
    remainder = units - sum(floors)
    ranking = sorted(range(len(shares)), key=lambda i: (-(shares[i] - floors[i]), i))
    for index in ranking[:remainder]:
        floors[index] += 1
    return [Decimal(value) * MONEY_QUANTUM for value in floors]


def calculate_maintenance_pricing(lines, *, tax_inclusive=False,
                                  discount_percent=ZERO, discount_value=ZERO):
    """Calculate document amounts with mixed VAT rates and explicit discounts.

    Discounts must be either a percentage or a fixed amount, not both. Tax is
    computed after discounts, grouped by tax treatment and rate, and allocated
    back to lines. No database state is read or changed.
    """
    with localcontext() as context:
        context.prec = 60
        if not isinstance(tax_inclusive, bool):
            raise ValidationError('طريقة احتساب الضريبة غير صالحة')
        percent = _number(discount_percent, 'نسبة خصم الأمر', PERCENT_QUANTUM, ONE_HUNDRED)
        value = _number(discount_value, 'قيمة خصم الأمر', MONEY_QUANTUM, MAX_MONEY)
        if percent and value:
            raise ValidationError('اختر نسبة خصم الأمر أو قيمته، وليس كليهما')

        prepared = []
        for line in lines:
            if not isinstance(line, PriceLine):
                raise ValidationError('بند التسعير غير صالح')
            qty = _number(line.quantity, 'الكمية', MONEY_QUANTUM, MAX_MONEY)
            price = _number(line.unit_price, 'سعر الوحدة', MONEY_QUANTUM, MAX_MONEY)
            rate = _number(line.tax_rate, 'معدل الضريبة', PERCENT_QUANTUM, ONE_HUNDRED)
            line_percent = _number(line.discount_percent, 'نسبة خصم البند', PERCENT_QUANTUM, ONE_HUNDRED)
            line_value = _number(line.discount_value, 'قيمة خصم البند', MONEY_QUANTUM, MAX_MONEY)
            if qty == ZERO:
                raise ValidationError('الكمية يجب أن تكون أكبر من صفر')
            if line.tax_treatment not in ('standard', 'zero', 'exempt'):
                raise ValidationError('المعاملة الضريبية غير صالحة')
            if line.tax_treatment in ('zero', 'exempt') and rate != ZERO:
                raise ValidationError('البند الصفري أو المعفى لا يحمل معدل ضريبة')
            if line.discount_mode not in ('percent', 'value'):
                raise ValidationError('طريقة خصم البند غير صالحة')
            if (line.discount_mode == 'percent' and line_value) or (line.discount_mode == 'value' and line_percent):
                raise ValidationError('اختر طريقة واحدة لخصم البند')
            original = _money(qty * price)
            line_discount = (_money(original * line_percent / ONE_HUNDRED)
                             if line.discount_mode == 'percent' else line_value)
            if line_discount > original:
                raise ValidationError('خصم البند يتجاوز قيمته')
            prepared.append({'original': original, 'line_discount': line_discount,
                             'basis': original - line_discount,
                             'tax_rate': rate, 'tax_treatment': line.tax_treatment})

        basis_subtotal = _money(sum((line['basis'] for line in prepared), ZERO))
        line_discount_total = _money(sum((line['line_discount'] for line in prepared), ZERO))
        order_discount = _money(basis_subtotal * percent / ONE_HUNDRED) if percent else value
        if order_discount > basis_subtotal:
            raise ValidationError('خصم الأمر يتجاوز قيمة البنود')
        discounts = _allocate(order_discount, [line['basis'] for line in prepared])
        bases = [line['basis'] - discount for line, discount in zip(prepared, discounts)]

        buckets = {}
        for index, line in enumerate(prepared):
            key = (line['tax_treatment'], line['tax_rate'])
            buckets.setdefault(key, []).append(index)
        taxes = [ZERO.quantize(MONEY_QUANTUM) for _ in prepared]
        for (treatment, rate), indexes in buckets.items():
            bucket_basis = sum((bases[index] for index in indexes), ZERO)
            if treatment != 'standard' or not rate or not bucket_basis:
                continue
            tax = (bucket_basis * rate / (ONE_HUNDRED + rate if tax_inclusive else ONE_HUNDRED))
            tax = tax.quantize(TAX_QUANTUM, rounding=ROUND_HALF_UP)
            for index, line_tax in zip(indexes, _allocate(tax, [bases[index] for index in indexes])):
                taxes[index] = line_tax

        calculated = []
        for line, order_part, basis, tax in zip(prepared, discounts, bases, taxes):
            net = basis - tax if tax_inclusive else basis
            calculated.append(CalculatedLine(
                original_amount=line['original'], line_discount=line['line_discount'],
                order_discount=order_part, net_amount=_money(net), tax_amount=tax,
                total_amount=_money(net + tax), tax_rate=line['tax_rate'],
                tax_treatment=line['tax_treatment'],
            ))
        net = _money(sum((line.net_amount for line in calculated), ZERO))
        tax = _money(sum((line.tax_amount for line in calculated), ZERO))
        total = _money(net + tax)
        return PricingTotals(basis_subtotal, line_discount_total, order_discount,
                             net, tax, total, tuple(calculated))
