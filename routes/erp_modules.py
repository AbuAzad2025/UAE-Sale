"""
ERP Extended Modules Routes
"""

from datetime import datetime, timezone
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models.erp_modules import (
    Quotation, PurchaseOrder, FiscalPeriod, StockTransfer,
    StockTake, DunningLetter, RecurringExpense, ProductLot,
    WarehouseBin, EInvoice,
)
from services.erp_modules_service import (
    QuotationService, PurchaseOrderService, FiscalPeriodService,
    StockTransferService, StockTakeService, DunningService,
    EInvoiceService,
)
from utils.decorators import permission_required, admin_required
from utils.helpers import create_audit_log

erp_bp = Blueprint('erp_modules', __name__, url_prefix='/erp')


# ==================== QUOTATIONS ====================

@erp_bp.route('/quotations')
@login_required
@permission_required('manage_sales')
def quotations():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '', type=str)
    query = Quotation.query
    if status:
        query = query.filter_by(status=status)
    pagination = query.order_by(Quotation.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('erp/quotations.html', quotations=pagination.items, pagination=pagination)


@erp_bp.route('/quotations/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_sales')
def create_quotation():
    if request.method == 'POST':
        try:
            from models import Customer
            customer_id = request.form.get('customer_id', type=int)
            lines_data = []
            i = 0
            while True:
                pid = request.form.get(f'lines[{i}][product_id]', type=int)
                if not pid:
                    break
                qty = request.form.get(f'lines[{i}][quantity]', type=float)
                price = request.form.get(f'lines[{i}][unit_price]', type=float)
                disc = request.form.get(f'lines[{i}][discount_percent]', 0, type=float)
                if pid and qty and qty > 0:
                    lines_data.append({'product_id': pid, 'quantity': qty, 'unit_price': price, 'discount_percent': disc})
                i += 1

            if not lines_data:
                flash('⚠️ يجب إضافة منتج واحد على الأقل', 'danger')
                return redirect(url_for('erp_modules.create_quotation'))

            q = QuotationService.create_quotation(
                customer_id=customer_id,
                seller_id=current_user.id,
                lines_data=lines_data,
                warehouse_id=request.form.get('warehouse_id', type=int),
                currency=request.form.get('currency', 'AED'),
                discount_amount=request.form.get('discount_amount', 0, type=float),
                tax_rate=request.form.get('tax_rate', 0, type=float),
                valid_days=request.form.get('valid_days', 30, type=int),
                notes=request.form.get('notes'),
            )
            create_audit_log('create', 'quotations', q.id)
            flash(f'✅ تم إنشاء عرض الأسعار {q.quotation_number}', 'success')
            return redirect(url_for('erp_modules.view_quotation', id=q.id))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    from models import Customer, Warehouse, Product  # noqa: F811  (local import intentional)
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return render_template('erp/create_quotation.html', customers=customers, warehouses=warehouses, products=products)


@erp_bp.route('/quotations/<int:id>')
@login_required
@permission_required('manage_sales')
def view_quotation(id):
    q = db.get_or_404(Quotation, id)
    return render_template('erp/view_quotation.html', quotation=q)


@erp_bp.route('/quotations/<int:id>/status', methods=['POST'])
@login_required
@permission_required('manage_sales')
def update_quotation_status(id):
    q = db.get_or_404(Quotation, id)
    new_status = request.form.get('status')
    if new_status in ('sent', 'accepted', 'rejected'):
        q.status = new_status
        db.session.commit()
        flash(f'✅ تم تحديث الحالة إلى {q.status_ar}', 'success')
    return redirect(url_for('erp_modules.view_quotation', id=id))


@erp_bp.route('/quotations/<int:id>/convert', methods=['POST'])
@login_required
@permission_required('manage_sales')
def convert_quotation(id):
    try:
        sale = QuotationService.convert_to_sale(id, current_user.id)
        create_audit_log('convert', 'quotations', id)
        flash(f'✅ تم التحويل إلى فاتورة {sale.sale_number}', 'success')
        return redirect(url_for('sales.view', id=sale.id))
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
        return redirect(url_for('erp_modules.view_quotation', id=id))


# ==================== PURCHASE ORDERS ====================

@erp_bp.route('/purchase-orders')
@login_required
@permission_required('manage_purchases')
def purchase_orders():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '', type=str)
    query = PurchaseOrder.query
    if status:
        query = query.filter_by(status=status)
    pagination = query.order_by(PurchaseOrder.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('erp/purchase_orders.html', orders=pagination.items, pagination=pagination)


@erp_bp.route('/purchase-orders/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_purchases')
def create_purchase_order():
    if request.method == 'POST':
        try:
            from models import Supplier, Warehouse, Product
            supplier_id = request.form.get('supplier_id', type=int)
            warehouse_id = request.form.get('warehouse_id', type=int)
            lines_data = []
            i = 0
            while True:
                pid = request.form.get(f'lines[{i}][product_id]', type=int)
                if not pid:
                    break
                qty = request.form.get(f'lines[{i}][quantity]', type=float)
                cost = request.form.get(f'lines[{i}][unit_cost]', type=float)
                if pid and qty and qty > 0 and cost:
                    lines_data.append({'product_id': pid, 'quantity': qty, 'unit_cost': cost})
                i += 1

            if not lines_data:
                flash('⚠️ يجب إضافة منتج واحد على الأقل', 'danger')
                return redirect(url_for('erp_modules.create_purchase_order'))

            exp_str = request.form.get('expected_delivery')
            exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date() if exp_str else None

            po = PurchaseOrderService.create_po(
                supplier_id=supplier_id,
                warehouse_id=warehouse_id,
                lines_data=lines_data,
                user_id=current_user.id,
                expected_delivery=exp_date,
                tax_rate=request.form.get('tax_rate', 0, type=float),
                notes=request.form.get('notes'),
            )
            create_audit_log('create', 'purchase_orders', po.id)
            flash(f'✅ تم إنشاء أمر الشراء {po.po_number}', 'success')
            return redirect(url_for('erp_modules.view_purchase_order', id=po.id))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    from models import Supplier, Warehouse, Product  # noqa: F811  (local import intentional)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return render_template('erp/create_purchase_order.html', suppliers=suppliers, warehouses=warehouses, products=products)


@erp_bp.route('/purchase-orders/<int:id>')
@login_required
@permission_required('manage_purchases')
def view_purchase_order(id):
    po = db.get_or_404(PurchaseOrder, id)
    return render_template('erp/view_purchase_order.html', order=po)


@erp_bp.route('/purchase-orders/<int:id>/submit', methods=['POST'])
@login_required
@permission_required('manage_purchases')
def submit_purchase_order(id):
    po = db.get_or_404(PurchaseOrder, id)
    if po.status == 'draft':
        po.status = 'submitted'
        db.session.commit()
        flash('✅ تم تقديم أمر الشراء', 'success')
    return redirect(url_for('erp_modules.view_purchase_order', id=id))


@erp_bp.route('/purchase-orders/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('manage_purchases')
def approve_purchase_order(id):
    try:
        po = PurchaseOrderService.approve_po(id, current_user.id)
        create_audit_log('approve', 'purchase_orders', po.id)
        flash('✅ تم اعتماد أمر الشراء', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('erp_modules.view_purchase_order', id=id))


@erp_bp.route('/purchase-orders/<int:id>/receive', methods=['POST'])
@login_required
@permission_required('manage_purchases')
def receive_purchase_order(id):
    try:
        purchase = PurchaseOrderService.receive_po(id, current_user.id)
        create_audit_log('receive', 'purchase_orders', id)
        flash(f'✅ تم الاستلام وإنشاء فاتورة {purchase.purchase_number}', 'success')
        return redirect(url_for('purchases.view', id=purchase.id))
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
        return redirect(url_for('erp_modules.view_purchase_order', id=id))


# ==================== FISCAL PERIODS ====================

@erp_bp.route('/fiscal-periods')
@login_required
@permission_required('manage_ledger')
def fiscal_periods():
    periods = FiscalPeriod.query.order_by(FiscalPeriod.year.desc()).all()
    return render_template('erp/fiscal_periods.html', periods=periods)


@erp_bp.route('/fiscal-periods/create', methods=['POST'])
@login_required
@permission_required('manage_ledger')
def create_fiscal_period():
    try:
        year = request.form.get('year', type=int)
        _ = FiscalPeriodService.create_annual_period(year)
        flash(f'✅ تم إنشاء الفترة المالية {year}', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('erp_modules.fiscal_periods'))


@erp_bp.route('/fiscal-periods/<int:id>/close', methods=['POST'])
@login_required
@admin_required
def close_fiscal_period(id):
    """Close fiscal period — admin only (owner/super_admin)"""
    try:
        FiscalPeriodService.close_period(id, current_user.id)
        create_audit_log('close', 'fiscal_periods', id)
        flash('✅ تم إغلاق الفترة المالية', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('erp_modules.fiscal_periods'))


@erp_bp.route('/fiscal-periods/<int:id>/reopen', methods=['POST'])
@login_required
@admin_required
def reopen_fiscal_period(id):
    """Reopen fiscal period — admin only (owner/super_admin)"""
    fp = db.get_or_404(FiscalPeriod, id)
    fp.reopen()
    db.session.commit()
    create_audit_log('reopen', 'fiscal_periods', id)
    flash('✅ تم إعادة فتح الفترة المالية', 'success')
    return redirect(url_for('erp_modules.fiscal_periods'))


# ==================== STOCK TRANSFERS ====================

@erp_bp.route('/stock-transfers')
@login_required
@permission_required('manage_warehouse')
def stock_transfers():
    transfers = StockTransfer.query.order_by(StockTransfer.created_at.desc()).all()
    return render_template('erp/stock_transfers.html', transfers=transfers)


@erp_bp.route('/stock-transfers/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_warehouse')
def create_stock_transfer():
    if request.method == 'POST':
        try:
            lines_data = []
            i = 0
            while True:
                pid = request.form.get(f'lines[{i}][product_id]', type=int)
                if not pid:
                    break
                qty = request.form.get(f'lines[{i}][quantity]', type=float)
                if pid and qty and qty > 0:
                    lines_data.append({'product_id': pid, 'quantity': qty})
                i += 1

            if not lines_data:
                flash('⚠️ يجب إضافة منتج واحد على الأقل', 'danger')
                return redirect(url_for('erp_modules.create_stock_transfer'))

            transfer = StockTransferService.create_transfer(
                from_warehouse_id=request.form.get('from_warehouse_id', type=int),
                to_warehouse_id=request.form.get('to_warehouse_id', type=int),
                lines_data=lines_data,
                user_id=current_user.id,
                notes=request.form.get('notes'),
            )
            flash(f'✅ تم إنشاء طلب النقل {transfer.transfer_number}', 'success')
            return redirect(url_for('erp_modules.stock_transfers'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    from models import Warehouse, Product
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return render_template('erp/create_stock_transfer.html', warehouses=warehouses, products=products)


@erp_bp.route('/stock-transfers/<int:id>/send', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def send_stock_transfer(id):
    t = db.get_or_404(StockTransfer, id)
    if t.status == 'pending':
        t.status = 'in_transit'
        db.session.commit()
        flash('✅ تم إرسال الشحنة', 'success')
    return redirect(url_for('erp_modules.stock_transfers'))


@erp_bp.route('/stock-transfers/<int:id>/receive', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def receive_stock_transfer(id):
    try:
        StockTransferService.receive_transfer(id, current_user.id)
        flash('✅ تم استلام الشحنة وتحديث المخزون', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('erp_modules.stock_transfers'))


# ==================== STOCK TAKES ====================

@erp_bp.route('/stock-takes')
@login_required
@permission_required('manage_warehouse')
def stock_takes():
    takes = StockTake.query.order_by(StockTake.created_at.desc()).all()
    from models import Warehouse
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.name).all()
    return render_template('erp/stock_takes.html', stock_takes=takes, warehouses=warehouses)


@erp_bp.route('/stock-takes/create', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def create_stocktake():
    try:
        st = StockTakeService.create_stocktake(
            warehouse_id=request.form.get('warehouse_id', type=int),
            user_id=current_user.id,
        )
        flash(f'✅ تم إنشاء جرد {st.stocktake_number}', 'success')
    except Exception as e:
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('erp_modules.stock_takes'))


@erp_bp.route('/stock-takes/<int:id>/count', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def update_stocktake_count(id):
    st = db.get_or_404(StockTake, id)
    for item in st.items:
        counted = request.form.get(f'counted_{item.id}', type=float)
        if counted is not None:
            item.counted_quantity = counted
            item.calculate_variance()
    st.status = 'completed'
    st.completed_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('✅ تم حفظ نتائج الجرد', 'success')
    return redirect(url_for('erp_modules.view_stocktake', id=id))


@erp_bp.route('/stock-takes/<int:id>')
@login_required
@permission_required('manage_warehouse')
def view_stocktake(id):
    st = db.get_or_404(StockTake, id)
    return render_template('erp/view_stocktake.html', stocktake=st)


@erp_bp.route('/stock-takes/<int:id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_stocktake(id):
    """Approve stock take and apply variances — admin only (owner/super_admin)"""
    try:
        StockTakeService.approve_stocktake(id, current_user.id)
        create_audit_log('approve', 'stock_takes', id)
        flash('✅ تم اعتماد الجرد وتحديث المخزون', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    return redirect(url_for('erp_modules.view_stocktake', id=id))


# ==================== DUNNING LETTERS ====================

@erp_bp.route('/dunning')
@login_required
@permission_required('manage_payments')
def dunning():
    letters = DunningLetter.query.order_by(DunningLetter.created_at.desc()).all()
    summary = DunningService.get_overdue_summary()
    return render_template('erp/dunning.html', letters=letters, summary=summary)


@erp_bp.route('/dunning/generate', methods=['POST'])
@login_required
@permission_required('manage_payments')
def generate_dunning():
    letters = DunningService.check_overdue_accounts()
    if letters:
        flash(f'✅ تم إنشاء {len(letters)} إنذار تحصيل', 'success')
    else:
        flash('ℹ️ لا يوجد حسابات متأخرة تحتاج إنذار', 'info')
    return redirect(url_for('erp_modules.dunning'))


@erp_bp.route('/dunning/<int:id>/send', methods=['POST'])
@login_required
@permission_required('manage_payments')
def send_dunning(id):
    letter = db.get_or_404(DunningLetter, id)
    letter.status = 'sent'
    letter.sent_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('✅ تم تسجيل إرسال الإنذار', 'success')
    return redirect(url_for('erp_modules.dunning'))


# ==================== RECURRING EXPENSES ====================

@erp_bp.route('/recurring-expenses')
@login_required
@permission_required('manage_expenses')
def recurring_expenses():
    expenses = RecurringExpense.query.order_by(RecurringExpense.next_due_date).all()
    return render_template('erp/recurring_expenses.html', recurring_expenses=expenses)


@erp_bp.route('/recurring-expenses/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_expenses')
def create_recurring_expense():
    if request.method == 'POST':
        try:
            from models import ExpenseCategory
            next_due = datetime.strptime(request.form.get('next_due_date'), '%Y-%m-%d').date()
            re = RecurringExpense(
                name=request.form.get('name'),
                category_id=request.form.get('category_id', type=int),
                amount=Decimal(str(request.form.get('amount', 0))),
                currency=request.form.get('currency', 'AED'),
                payment_method=request.form.get('payment_method', 'bank_transfer'),
                supplier_name=request.form.get('supplier_name'),
                description=request.form.get('description'),
                frequency=request.form.get('frequency', 'monthly'),
                next_due_date=next_due,
            )
            db.session.add(re)
            db.session.commit()
            flash('✅ تم إنشاء المصروف الدوري', 'success')
            return redirect(url_for('erp_modules.recurring_expenses'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    from models import ExpenseCategory  # noqa: F811  (local import intentional)
    categories = ExpenseCategory.query.filter_by(is_active=True).all()
    return render_template('erp/create_recurring_expense.html', categories=categories)


@erp_bp.route('/recurring-expenses/<int:id>/toggle', methods=['POST'])
@login_required
@permission_required('manage_expenses')
def toggle_recurring_expense(id):
    re = db.get_or_404(RecurringExpense, id)
    re.is_active = not re.is_active
    db.session.commit()
    flash(f'✅ تم {"تفعيل" if re.is_active else "إيقاف"} المصروف الدوري', 'success')
    return redirect(url_for('erp_modules.recurring_expenses'))


# ==================== LOT TRACKING ====================

@erp_bp.route('/lots')
@login_required
@permission_required('manage_warehouse')
def lots():
    lots = ProductLot.query.filter_by(is_active=True).order_by(ProductLot.created_at.desc()).all()
    return render_template('erp/lots.html', lots=lots)


@erp_bp.route('/lots/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_warehouse')
def create_lot():
    if request.method == 'POST':
        try:
            from models import Product, Warehouse
            lot = ProductLot(
                product_id=request.form.get('product_id', type=int),
                lot_number=request.form.get('lot_number'),
                warehouse_id=request.form.get('warehouse_id', type=int),
                quantity=Decimal(str(request.form.get('quantity', 0))),
                cost_price=Decimal(str(request.form.get('cost_price', 0))),
                manufacture_date=datetime.strptime(request.form.get('manufacture_date'), '%Y-%m-%d').date() if request.form.get('manufacture_date') else None,
                expiry_date=datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date() if request.form.get('expiry_date') else None,
                purchase_id=request.form.get('purchase_id', type=int),
            )
            db.session.add(lot)
            db.session.commit()
            flash('✅ تم إنشاء الدفعة', 'success')
            return redirect(url_for('erp_modules.lots'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    from models import Product, Warehouse  # noqa: F811  (local import intentional)
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    return render_template('erp/create_lot.html', products=products, warehouses=warehouses)


# ==================== BIN TRACKING ====================

@erp_bp.route('/bins')
@login_required
@permission_required('manage_warehouse')
def bins():
    from models import Warehouse
    bins = WarehouseBin.query.filter_by(is_active=True).order_by(WarehouseBin.warehouse_id, WarehouseBin.code).all()
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    return render_template('erp/bins.html', bins=bins, warehouses=warehouses)


@erp_bp.route('/bins/create', methods=['POST'])
@login_required
@permission_required('manage_warehouse')
def create_bin():
    try:
        bin = WarehouseBin(
            warehouse_id=request.form.get('warehouse_id', type=int),
            code=request.form.get('code'),
            name=request.form.get('name'),
            aisle=request.form.get('aisle'),
            shelf=request.form.get('shelf'),
            position=request.form.get('position'),
            capacity=request.form.get('capacity', 0, type=int),
        )
        db.session.add(bin)
        db.session.commit()
        flash('✅ تم إنشاء الموقع', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('erp_modules.bins'))


# ==================== E-INVOICING ====================

@erp_bp.route('/e-invoices')
@login_required
@permission_required('manage_sales')
def e_invoices():
    invoices = EInvoice.query.order_by(EInvoice.created_at.desc()).all()
    return render_template('erp/e_invoices.html', e_invoices=invoices)


@erp_bp.route('/e-invoices/generate/<int:sale_id>', methods=['POST'])
@login_required
@permission_required('manage_sales')
def generate_einvoice(sale_id):
    try:
        einv = EInvoiceService.create_einvoice(sale_id)
        create_audit_log('create', 'e_invoices', einv.id)
        flash(f'✅ تم إنشاء الفاتورة الإلكترونية {einv.invoice_number}', 'success')
    except Exception as e:
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('erp_modules.e_invoices'))


@erp_bp.route('/e-invoices/<int:id>')
@login_required
@permission_required('manage_sales')
def view_einvoice(id):
    einv = db.get_or_404(EInvoice, id)
    return render_template('erp/view_einvoice.html', einvoice=einv)
