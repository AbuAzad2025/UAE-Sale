from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import current_app
from extensions import db
from models import Sale, SaleLine, ProductReturn, ProductReturnLine, Product
from services.stock_service import StockService
from services.gl_service import GLService
from services.tax_engine import TaxEngine
from utils.decorators import get_owned_or_404, get_owned_or_raise
from utils.errors import ValidationError
from utils.helpers import generate_number, create_audit_log


def _refund_exchange_rate(sale):
    """Rate used to value a refund — never silently defaulted to 1.0.

    A wrong rate changes the cash paid to the customer and the AR credit, so
    an absent/invalid invoice rate is a blocking validation error rather than
    an arbitrary fallback.
    """
    raw = getattr(sale, "exchange_rate", None)
    try:
        rate = Decimal(str(raw))
    except (TypeError, ValueError, InvalidOperation):
        raise ValidationError("سعر صرف الفاتورة غير صالح — لا يمكن حساب الاسترداد") from None
    if not rate.is_finite() or rate <= Decimal("0"):
        raise ValidationError("سعر صرف الفاتورة غير صالح — لا يمكن حساب الاسترداد")
    return rate


class ReturnService:
    @staticmethod
    def create_return(  # noqa: C901
        sale_id, return_lines_data, user_id=None, notes=None, auto_approve=False
    ):
        """
        Create a product return (Sales Return) with financial and stock updates.

        Args:
            sale_id (int): The ID of the sale being returned.
            return_lines_data (list): List of dicts containing:
                - sale_line_id (int)
                - quantity (float/Decimal)
                - condition (str)
                - notes (str)
            user_id (int): ID of the user processing the return.
            notes (str): General notes for the return.
            auto_approve (bool): Legacy escape hatch — pass True to finalise a
                return immediately. The default is ``False``: returns are
                created ``pending`` and must be finalised via
                :meth:`approve_return` (which re-derives the customer balance
                and the invoice settlement).

        Returns:
            ProductReturn: The created return record.
        """
        try:
            sale = get_owned_or_raise(Sale, sale_id)
            if not sale:
                raise ValueError(f"Sale with ID {sale_id} not found.")
            if sale.status == "cancelled":
                raise ValueError("Cannot create return for a cancelled sale.")

            refund_rate = _refund_exchange_rate(sale)
            return_number = generate_number("R", ProductReturn, "return_number")

            product_return = ProductReturn(
                return_number=return_number,
                sale_id=sale.id,
                customer_id=sale.customer_id,
                currency=sale.currency,
                exchange_rate=refund_rate,
                notes=notes,
                processed_by=user_id,
                # Returns are recorded pending and require an explicit
                # approval — automatic approval bypassed the control and made
                # the balance/stock effects impossible to review.
                status="approved" if auto_approve else "pending",
            )

            product_return.total_amount = Decimal("0")
            product_return.refund_amount = Decimal("0")
            product_return.amount_base = Decimal("0")

            db.session.add(product_return)
            db.session.flush()  # Get ID

            total_return_amount = Decimal("0")
            return_line_specs = []
            gl_lines = []
            # Cost/COGS reversal is already in BASE currency (SaleLine.cost_price is base).
            # It must be posted at exchange_rate=1 in a separate entry, never mixed into
            # the transaction-currency revenue/VAT entry.
            cost_gl_lines = []
            review_flags = []

            routing = TaxEngine.liability_routing()

            for line_data in return_lines_data:
                sale_line_id = line_data.get("sale_line_id")
                quantity = Decimal(str(line_data.get("quantity", 0)))

                if quantity <= 0:
                    continue

                sale_line = get_owned_or_raise(SaleLine, sale_line_id, for_update=True)
                if not sale_line:
                    raise ValueError(f"Sale line {sale_line_id} not found.")
                if sale_line.sale_id != sale.id:
                    raise ValueError(
                        f"Sale line {sale_line_id} does not belong to sale {sale.id}."
                    )

                # Effects are applied at creation, so a pending return also
                # consumes sold quantity — otherwise two pending returns could
                # each return the same units.
                previous_returned = db.session.query(
                    db.func.sum(ProductReturnLine.quantity)
                ).join(ProductReturn).filter(
                    ProductReturnLine.sale_line_id == sale_line.id,
                    ProductReturn.status.in_(["pending", "approved"]),
                ).scalar() or Decimal("0")

                if (previous_returned + quantity) > sale_line.quantity:
                    raise ValueError(
                        f"Cannot return {quantity} of {sale_line.product.name}. Already returned: {previous_returned}, Sold: {sale_line.quantity}."
                    )  # noqa: E501

                unit_price = Decimal(str(sale_line.unit_price or 0))
                discount_percent = Decimal(str(sale_line.discount_percent or 0))
                if discount_percent < Decimal("0") or discount_percent > Decimal("100"):
                    discount_percent = Decimal("0")
                net_multiplier = (Decimal("100") - discount_percent) / Decimal("100")
                line_total = (unit_price * quantity * net_multiplier).quantize(
                    Decimal("0.001"), rounding=ROUND_HALF_UP
                )

                total_return_amount += line_total
                return_line_specs.append(
                    {
                        "line_total": line_total,
                        "tax_treatment": getattr(sale_line, "tax_treatment", None)
                        or "standard",
                    }
                )

                return_line = ProductReturnLine(
                    return_id=product_return.id,
                    sale_line_id=sale_line.id,
                    product_id=sale_line.product_id,
                    quantity=quantity,
                    unit_price=unit_price,
                    line_total=line_total,
                    condition=line_data.get("condition"),
                    notes=line_data.get("notes"),
                )
                db.session.add(return_line)

                StockService.create_movement(
                    product_id=sale_line.product_id,
                    quantity=quantity,
                    movement_type="return",
                    reference_type="ProductReturn",
                    reference_id=product_return.id,
                    notes=f"Return for Sale {sale.sale_number}",
                    warehouse_id=sale.warehouse_id,  # Return to same warehouse
                )

                product = get_owned_or_404(Product, sale_line.product_id)
                line_cost = sale_line.cost_price
                reliable = line_cost is not None and Decimal(str(line_cost)) > Decimal(
                    "0"
                )
                if reliable:
                    cost_price = Decimal(str(line_cost))
                else:
                    product_cost = product.cost_price if product is not None else None
                    if product_cost is not None and Decimal(
                        str(product_cost)
                    ) > Decimal("0"):
                        cost_price = Decimal(str(product_cost))
                        review_flags.append(
                            f"سطر البيع {sale_line.id}: لا توجد تكلفة موثّقة "
                            f"(cost_price = {line_cost}) — عُكس القيد بتكلفة "
                            f"المنتج الحالية {cost_price} وبحاجة إلى مراجعة."
                        )
                        current_app.logger.error(
                            "Return %s: sale line %s has no reliable cost "
                            "(cost_price=%s); reversed at the product current "
                            "cost %s — manual review required.",
                            product_return.return_number,
                            sale_line.id,
                            line_cost,
                            cost_price,
                        )
                    else:
                        raise ValidationError(
                            f"لا يمكن عكس تكلفة البضاعة للمنتج "
                            f'"{sale_line.product.name if sale_line.product else sale_line.product_id}": '
                            f"لا توجد تكلفة على سطر البيع ولا تكلفة حالية للمنتج. "
                            f"💡 اضبط تكلفة المنتج ثم أعد تنفيذ المرتجع."
                        )

                cost_value = (quantity * cost_price).quantize(
                    Decimal("0.001"), rounding=ROUND_HALF_UP
                )

                if cost_value > 0:
                    cost_gl_lines.append(
                        {
                            "account": routing["inventory"],
                            "debit": cost_value,
                            "credit": 0,
                            "description": f"Inventory Restock - {product.name}",
                        }
                    )
                    cost_gl_lines.append(
                        {
                            "account": routing["cogs"],
                            "debit": 0,
                            "credit": cost_value,
                            "description": f"COGS Reversal - {product.name}",
                        }
                    )

            product_return.calculate_totals()

            if review_flags:
                marker = "\n[مراجعة مطلوبة] " + " | ".join(review_flags)
                product_return.notes = (product_return.notes or "") + marker

            tax_rate = Decimal(str(sale.tax_rate or 0))
            invoice_treatment = getattr(sale, "tax_treatment", "standard") or "standard"
            shipping = Decimal(str(sale.shipping_cost or 0))
            discount = Decimal(str(sale.discount_amount or 0))
            from services.sale_tax_calculation import return_tax_parts

            tax_amount, net_std, net_zero, net_exempt = return_tax_parts(
                return_line_specs,
                sale.lines,
                sale.subtotal,
                discount,
                shipping,
                tax_rate,
                bool(sale.tax_inclusive),
                invoice_treatment=invoice_treatment,
            )

            net_return_amount = (net_std + net_zero + net_exempt).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            gross_return_amount = (net_return_amount + tax_amount).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )

            product_return.refund_amount = (
                gross_return_amount  # Default to full refund of value
            )

            gl_lines.append(
                {
                    "account": routing["sales_returns"],
                    "debit": net_return_amount,
                    "credit": 0,
                    "description": f"Sales Return Revenue Reversal {sale.sale_number}",
                }
            )

            if tax_amount > 0:
                gl_lines.append(
                    {
                        "account": routing["output_vat"],
                        "debit": tax_amount,
                        "credit": 0,
                        "description": f"Sales Return Tax Reversal {sale.sale_number}",
                    }
                )

            _return_party = (
                sale.customer.id
                if getattr(sale.customer, "customer_type", None) == "partner"
                else None
            )
            gl_lines.append(
                {
                    "account": GLService.get_customer_credit_account(sale.customer),
                    "debit": 0,
                    "credit": gross_return_amount,
                    "description": f"Credit Customer for Return {sale.sale_number}",
                    **({"party_id": _return_party} if _return_party else {}),
                }
            )

            from services.partner_profit import post_partner_shares_for_return

            post_partner_shares_for_return(product_return, sale)

            if gl_lines:
                GLService.post_entry(
                    lines=gl_lines,
                    description=f"Sales Return {product_return.return_number} for Sale {sale.sale_number}",
                    reference_type="ProductReturn",
                    reference_id=product_return.id,
                    currency=sale.currency,
                    exchange_rate=refund_rate,
                    idempotency_key=f"ProductReturn:{product_return.id}:revenue",
                )

            # Post the COGS/inventory reversal at BASE currency (rate=1) in its
            # own balanced entry. Using the sale's FX rate here would multiply
            # an already-base-valued cost by the rate (3.65x overstatement).
            if cost_gl_lines:
                from services.currency_service import CurrencyService as _CS

                GLService.post_entry(
                    lines=cost_gl_lines,
                    description=f"Sales Return Cost Reversal {product_return.return_number} for Sale {sale.sale_number}",
                    reference_type="ProductReturnCost",
                    reference_id=product_return.id,
                    currency=_CS.get_base_currency(),
                    exchange_rate=1,
                    idempotency_key=f"ProductReturn:{product_return.id}:cost",
                )

            from services.currency_service import CurrencyService
            from models import Payment

            _rate = refund_rate
            refund_base = (gross_return_amount * _rate).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            paid_base = Decimal(str(sale.paid_amount_base or 0))
            cash_out_base = min(paid_base, refund_base)
            ar_part_base = refund_base - cash_out_base
            if cash_out_base > 0:
                _ar_acct = GLService.get_customer_credit_account(sale.customer)
                _cash_acct = GLService.get_payment_debit_account(
                    "cash", tenant_id=sale.tenant_id
                )
                _refund_party = (
                    sale.customer.id
                    if getattr(sale.customer, "customer_type", None) == "partner"
                    else None
                )
                GLService.post_entry(
                    [
                        {
                            "account": _ar_acct,
                            "debit": cash_out_base,
                            "description": f"تسوية مرتجع نقدي {product_return.return_number}",
                            **({"party_id": _refund_party} if _refund_party else {}),
                        },
                        {
                            "account": _cash_acct,
                            "credit": cash_out_base,
                            "description": f"صرف مسترد {product_return.return_number}",
                            **({"party_id": _refund_party} if _refund_party else {}),
                        },
                    ],
                    description=f"Cash refund {product_return.return_number} for Sale {sale.sale_number}",
                    reference_type="ProductReturn",
                    reference_id=product_return.id,
                    currency=CurrencyService.get_base_currency(),
                    exchange_rate=1,
                    idempotency_key=f"ProductReturn:{product_return.id}:cash",
                )
                cash_out_txn = (cash_out_base / _rate).quantize(
                    Decimal("0.001"), rounding=ROUND_HALF_UP
                )
                db.session.add(
                    Payment(
                        payment_number=generate_number(
                            "PAY", Payment, "payment_number"
                        ),
                        payment_type="refund",
                        direction="outgoing",
                        sale_id=sale.id,
                        customer_id=sale.customer_id,
                        amount=cash_out_txn,
                        currency=sale.currency,
                        exchange_rate=_rate,
                        amount_base=cash_out_base,
                        payment_method="cash",
                        notes=f"استرداد نقدي للمرتجع {product_return.return_number}",
                        user_id=user_id,
                    )
                )

            db.session.flush()
            from models.sale import recompute_sale_settlement

            recompute_sale_settlement(sale.id, connection=db.session.connection())

            from models.customer import recompute_customer_balance

            recompute_customer_balance(sale.customer_id)

            create_audit_log(
                "create",
                "product_returns",
                product_return.id,
                changes={
                    "return_number": product_return.return_number,
                    "sale_id": sale.id,
                    "sale_number": sale.sale_number,
                    "customer_id": sale.customer_id,
                    "total_amount": str(product_return.total_amount),
                    "refund_amount": str(gross_return_amount),
                    "net_amount": str(net_return_amount),
                    "tax_amount": str(tax_amount),
                    "tax_rate": str(tax_rate),
                    "cash_refund_base": str(cash_out_base),
                    "ar_credit_base": str(ar_part_base),
                    "currency": sale.currency,
                    "exchange_rate": str(_rate),
                    "review_flags": review_flags,
                },
                commit=False,
            )

            db.session.flush()
            return product_return

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to create return: {e}")
            raise e

    @staticmethod
    def approve_return(product_return_id, user_id=None, notes=None):
        """Finalise a pending sales return.

        The after_update listener in ``models/events.py`` re-derives the
        customer balance and the invoice settlement when the status enters
        (or leaves) ``approved`` — so no balance formula is duplicated here.
        Calling this twice is a no-op.
        """
        product_return = get_owned_or_raise(ProductReturn, product_return_id)
        if product_return is None:
            raise ValueError(f"Product return {product_return_id} not found")
        if product_return.status == "approved":
            return product_return

        from models.sale import recompute_sale_settlement

        product_return.status = "approved"
        product_return.processed_by = user_id or product_return.processed_by
        if notes:
            product_return.notes = (product_return.notes or "") + f"\n[اعتماد] {notes}"
        db.session.flush()

        recompute_sale_settlement(
            product_return.sale_id, connection=db.session.connection()
        )
        from models.customer import recompute_customer_balance

        recompute_customer_balance(product_return.customer_id)

        create_audit_log(
            "approve",
            "product_returns",
            product_return.id,
            changes={
                "status": "approved",
                "return_number": product_return.return_number,
                "refund_amount": str(product_return.refund_amount),
            },
            commit=False,
        )
        db.session.flush()
        return product_return
