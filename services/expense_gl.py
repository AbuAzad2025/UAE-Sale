"""قيد المصروف الذري (GL) — نفس منطق ضريبة الشراء على مستند المصروف:

  * خاضعة/صفرية/معفاة + إجمالي (افتراضي: amount = أساس قبل الضريبة ويُضاف)
    أو شامل الضريبة (tax_inclusive=True ⇒ تُستخرج النسبة من المبلغ).
  * ضريبة غير قابلة للاسترداد ⇒ الضريبة تُضاف لتكلفة المصروف.
  * Reverse Charge (مورد أجنبي) ⇒ المورد بالصافي فقط (إن كان RC) أو الإجمالي،
    أما الضريبة الذاتية فتُسجَّل مدخلاً ومخرجاً بنفس الوقت.

الدفع يُكوَّن من (النقود/البنك/ذمم دائنة عبر شيك) — لا شيء يتوقّف على حساب محدد
غير أدوار `AccountRole` و `AccountResolver`.
"""

from decimal import Decimal, ROUND_HALF_UP

from services.account_resolution import AccountResolver, AccountRole

_Q = Decimal("0.01")
_MONEY_Q = Decimal("0.001")


def _d(value):
    return Decimal(str(value or 0))


def compute_expense_tax(amount, tax_rate, tax_inclusive, tax_treatment):
    """يعيد (net, tax, total) بالعملة المعاملة."""
    amount = _d(amount)
    rate = _d(tax_rate)
    treatment = (tax_treatment or "standard").strip().lower()
    if treatment in ("zero", "exempt"):
        rate = Decimal("0")
    if tax_inclusive:
        if rate <= 0:
            return amount, Decimal("0"), amount
        divisor = Decimal("1") + rate / Decimal("100")
        net = (amount / divisor).quantize(_Q, rounding=ROUND_HALF_UP)
        tax = (amount - net).quantize(_Q, rounding=ROUND_HALF_UP)
        return net, tax, amount
    tax = (amount * rate / Decimal("100")).quantize(_Q, rounding=ROUND_HALF_UP)
    return amount, tax, amount + tax


def build_expense_gl_lines(expense):
    """يبني سطور القيد من كائن المصروف. يعيد قائمة dictionaries."""
    tid = getattr(expense, "tenant_id", None)
    method = getattr(expense, "payment_method", "cash")
    num = getattr(expense, "expense_number", "") or ""
    tid = getattr(expense, "tenant_id", None)

    net, tax, total = compute_expense_tax(
        getattr(expense, "amount", 0),
        getattr(expense, "tax_rate", 0),
        bool(getattr(expense, "tax_inclusive", False)),
        getattr(expense, "tax_treatment", "standard"),
    )
    net = net.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    total = total.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    tax = tax.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)

    recoverable = bool(getattr(expense, "vat_recoverable", True))
    reverse_charge = bool(getattr(expense, "reverse_charge", False))

    category = getattr(expense, "category", None)
    expense_account = (
        category.gl_account_code if category and category.gl_account_code else "6990"
    )

    if method == "cash":
        payment_account = AccountResolver.resolve(AccountRole.CASH, tenant_id=tid)
    elif method == "cheque":
        payment_account = AccountResolver.resolve(AccountRole.AP_CONTROL, tenant_id=tid)
    else:
        payment_account = AccountResolver.resolve(AccountRole.BANK, tenant_id=tid)

    vat_input = AccountResolver.resolve(AccountRole.VAT_INPUT, tenant_id=tid)
    vat_output = AccountResolver.resolve(AccountRole.VAT_OUTPUT, tenant_id=tid)

    lines = []
    description = getattr(expense, "description", "") or ""

    if reverse_charge:
        if recoverable:
            lines.append(
                {"account": expense_account, "debit": net, "description": description}
            )
            if tax > 0:
                lines.append(
                    {
                        "account": vat_input,
                        "debit": tax,
                        "description": f"ضريبة المدخلات (Reverse Charge) {num}",
                    }
                )
                lines.append(
                    {
                        "account": vat_output,
                        "credit": tax,
                        "description": f"ضريبة المخرجات (Reverse Charge) {num}",
                    }
                )
            lines.append(
                {
                    "account": payment_account,
                    "credit": net,
                    "description": f"دفع {method}",
                }
            )
        else:
            gross = (net + tax).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
            lines.append(
                {"account": expense_account, "debit": gross, "description": description}
            )
            if tax > 0:
                lines.append(
                    {
                        "account": vat_output,
                        "credit": tax,
                        "description": f"ضريبة المخرجات (Reverse Charge) {num}",
                    }
                )
            lines.append(
                {
                    "account": payment_account,
                    "credit": net,
                    "description": f"دفع {method}",
                }
            )
        return lines

    if recoverable:
        lines.append(
            {"account": expense_account, "debit": net, "description": description}
        )
        if tax > 0:
            lines.append(
                {
                    "account": vat_input,
                    "debit": tax,
                    "description": f"ضريبة المدخلات (شراء) {num}",
                }
            )
        lines.append(
            {
                "account": payment_account,
                "credit": total,
                "description": f"دفع {method}",
            }
        )
    else:
        gross = (net + tax).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
        lines.append(
            {
                "account": expense_account,
                "debit": gross,
                "description": f"{description} (تشمل ضريبة غير قابلة للاسترداد)",
            }
        )
        lines.append(
            {
                "account": payment_account,
                "credit": gross,
                "description": f"دفع {method}",
            }
        )
    return lines


def expense_payment_amount(expense):
    """إجمالي النقد المدفوع فعليًا (صافي للـ RC، إجمالي لغيرها)."""
    net, tax, total = compute_expense_tax(
        getattr(expense, "amount", 0),
        getattr(expense, "tax_rate", 0),
        bool(getattr(expense, "tax_inclusive", False)),
        getattr(expense, "tax_treatment", "standard"),
    )
    if getattr(expense, "reverse_charge", False):
        return net
    return total


def expense_amount_base(expense):
    """المدفوع × سعر الصرف (تعمل مرجعية للتقريرات)."""
    rate = _d(getattr(expense, "exchange_rate", 1)) or Decimal("1")
    if rate <= 0:
        rate = Decimal("1")
    return (expense_payment_amount(expense) * rate).quantize(_Q, rounding=ROUND_HALF_UP)
