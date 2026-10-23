"""Bad debt write-offs — routes/writeoffs.py.

The surface of the write-off: list, create form, create, detail and void.

The gates are the ones the rest of the accounting surface uses: reading the
write-offs needs ``view_ledger`` and writing one needs ``manage_ledger``
(both are real permission codes — utils/system_init.py). The pages render the
repo's standard templates; the same paths answer JSON when the caller asks
for it explicitly, so the surface is usable from a script as well.
"""
from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import login_required

from models import Customer, Sale
from services.currency_service import CurrencyService
from services.writeoff_service import WriteOffService
from utils.decorators import get_owned_or_404, permission_required
from utils.errors import ValidationError

writeoffs_bp = Blueprint('writeoffs', __name__, url_prefix='/writeoffs')


def _wants_json():
    """هل يطلب المستدعي JSON صراحةً؟"""
    if request.args.get('format') == 'json':
        return True
    return bool(request.is_json)


@writeoffs_bp.route('/')
@login_required
@permission_required('view_ledger')
def index():
    """قائمة المشطوبات مع فلاتر العميل والحالة."""
    status = (request.args.get('status') or '').strip()
    customer_id = request.args.get('customer_id', type=int)

    write_offs = WriteOffService.list_writeoffs(
        customer=customer_id, status=status or None, limit=500)

    if _wants_json():
        return {
            'success': True,
            'count': len(write_offs),
            'write_offs': [wo.to_dict() for wo in write_offs],
        }

    return render_template(
        'writeoffs/index.html',
        write_offs=write_offs,
        selected_status=status,
        selected_customer_id=customer_id,
    )


@writeoffs_bp.route('/new', methods=['GET'])
@login_required
@permission_required('manage_ledger')
def new():
    """نموذج المشطوبة الجديدة."""
    customer_id = request.args.get('customer_id', type=int)

    customer = None
    if customer_id:
        customer = get_owned_or_404(Customer, customer_id)

    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    sales_query = Sale.query.filter(
        Sale.status == 'confirmed', Sale.is_active.is_(True))
    if customer is not None:
        sales_query = sales_query.filter(
            Sale.customer_id == customer.id, Sale.balance_due > 0)
    sales = sales_query.order_by(Sale.sale_date.desc()).limit(200).all()

    return render_template(
        'writeoffs/new.html',
        customers=customers,
        selected_customer=customer,
        sales=sales,
        base_currency=CurrencyService.get_base_currency(),
    )


@writeoffs_bp.route('/', methods=['POST'])
@login_required
@permission_required('manage_ledger')
def create():
    """تنفيذ المشطوبة وترحيل القيد."""
    customer_id = request.form.get('customer_id', type=int)
    sale_id = request.form.get('sale_id', type=int)
    amount = request.form.get('amount')
    currency = request.form.get('currency')
    reason = request.form.get('reason')
    notes = request.form.get('notes')

    customer = get_owned_or_404(Customer, customer_id)
    sale = get_owned_or_404(Sale, sale_id) if sale_id else None

    try:
        write_off = WriteOffService.create_writeoff(
            customer=customer,
            amount=amount,
            currency=currency,
            reason=reason,
            sale=sale,
            notes=notes,
        )
    except ValidationError as e:
        flash(str(e), 'danger')
        return redirect(url_for('writeoffs.new'))
    except Exception:
        current_app.logger.exception('Write-off creation failed')
        flash('حدث خطأ غير متوقع أثناء تنفيذ المشطوبة', 'danger')
        return redirect(url_for('writeoffs.new'))

    if _wants_json():
        return {'success': True, 'write_off': write_off.to_dict()}

    flash('تم تشطيب المديونية وترحيل القيد المحاسبي بنجاح', 'success')
    return redirect(url_for('writeoffs.detail', write_off_id=write_off.id))


@writeoffs_bp.route('/<int:write_off_id>')
@login_required
@permission_required('view_ledger')
def detail(write_off_id):
    """تفاصيل المشطوبة وقيدها المحاسبي."""
    write_off = WriteOffService.get_writeoff(write_off_id)
    if write_off is None:
        abort(404)

    if _wants_json():
        return {'success': True, 'write_off': write_off.to_dict()}

    return render_template('writeoffs/detail.html', write_off=write_off)


@writeoffs_bp.route('/<int:write_off_id>/void', methods=['POST'])
@login_required
@permission_required('manage_ledger')
def void(write_off_id):
    """إلغاء المشطوبة: عكس القيد وإعادة رصيد العميل."""
    write_off = WriteOffService.get_writeoff(write_off_id)
    if write_off is None:
        abort(404)

    try:
        WriteOffService.void_writeoff(
            write_off, reason=request.form.get('reason'))
    except ValidationError as e:
        flash(str(e), 'danger')
        return redirect(url_for('writeoffs.detail', write_off_id=write_off_id))
    except Exception:
        current_app.logger.exception('Write-off void failed')
        flash('حدث خطأ غير متوقع أثناء إلغاء المشطوبة', 'danger')
        return redirect(url_for('writeoffs.detail', write_off_id=write_off_id))

    if _wants_json():
        return {'success': True, 'write_off': write_off.to_dict()}

    flash('تم إلغاء المشطوبة وعكس القيد المحاسبي', 'success')
    return redirect(url_for('writeoffs.detail', write_off_id=write_off_id))
