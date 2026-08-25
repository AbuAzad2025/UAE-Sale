from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from extensions import db, limiter
from models import Purchase, PurchaseLine, Product, Supplier, Warehouse
from services.stock_service import StockService
from services.currency_service import CurrencyService
from services.gl_service import GLService
from utils.decorators import permission_required
from utils.helpers import create_audit_log, generate_number
from decimal import Decimal

purchases_bp = Blueprint('purchases', __name__, url_prefix='/purchases')


@purchases_bp.route('/')
@login_required
@permission_required('manage_purchases')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)

    query = Purchase.query

    if search:
        search_filter = f'%{search}%'
        query = query.filter(
            db.or_(
                Purchase.purchase_number.ilike(search_filter),
                Purchase.supplier_name.ilike(search_filter)
            )
        )

    query = query.filter_by(status='confirmed')

    pagination = query.order_by(Purchase.purchase_date.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    return render_template('purchases/index.html',
                           purchases=pagination.items,
                           pagination=pagination)


@purchases_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_purchases')
@limiter.limit("10 per minute", methods=['POST'])
def create():  # noqa: C901
    warehouse_id_val = request.form.get('warehouse_id', type=int) if request.method == 'POST' else None

    if request.method == 'POST':
        try:
            current_app.logger.info("POST request received for purchase creation")
            current_app.logger.info(f"Form data keys: {list(request.form.keys())}")
            current_app.logger.info(f"Line count from form: {request.form.get('line_count')}")

            purchase_number = generate_number('P', Purchase, 'purchase_number')

            # الحصول على معلومات المورد
            supplier_id = request.form.get('supplier_id', type=int)
            supplier = None
            supplier_name = request.form.get('supplier_name', '')
            supplier_phone = request.form.get('supplier_phone', '')
            supplier_email = request.form.get('supplier_email', '')
            if not warehouse_id_val:
                flash('⚠️ يجب اختيار المستودع الذي ستُضاف إليه البضاعة.', 'danger')
                return redirect(url_for('purchases.create'))

            # إذا تم اختيار مورد من القائمة
            if supplier_id:
                supplier = db.session.get(Supplier, supplier_id)
                if supplier:
                    supplier_name = supplier.name
                    supplier_phone = supplier.phone or ''
                    supplier_email = supplier.email or ''

            # التحقق من وجود اسم المورد
            if not supplier_name:
                flash('⚠️ يجب إدخال اسم المورد.\n💡 اكتب اسم المورد أو اختر من القائمة.', 'danger')
                return redirect(url_for('purchases.create'))

            currency_value = request.form.get('currency')
            currency = currency_value if currency_value else 'AED'
            user_exchange_rate = request.form.get('exchange_rate', type=float)

            exchange_rate = CurrencyService.get_exchange_rate(
                currency,
                'AED',
                user_rate=user_exchange_rate
            )

            purchase = Purchase(
                purchase_number=purchase_number,
                supplier_id=supplier_id,
                warehouse_id=warehouse_id_val,
                supplier_name=supplier_name,
                supplier_phone=supplier_phone,
                supplier_email=supplier_email,
                currency=currency,
                exchange_rate=exchange_rate,
                discount_amount=request.form.get('discount_amount', type=float, default=0),
                tax_rate=request.form.get('tax_rate', type=float, default=0),
                notes=request.form.get('notes'),
                user_id=current_user.id,
                subtotal=0,
                tax_amount=0,
                total_amount=0,
                amount_base=0
            )

            db.session.add(purchase)
            db.session.flush()

            line_count = int(request.form.get('line_count', 0))
            current_app.logger.info(f"Processing {line_count} lines")

            # طباعة جميع البيانات المرسلة
            for key, value in request.form.items():
                if key.startswith('lines['):
                    current_app.logger.info(f"Line data: {key} = {value}")

            current_app.logger.info("Starting to process lines...")
            lines_added = 0
            for i in range(line_count):
                product_id = request.form.get(f'lines[{i}][product_id]', type=int)
                quantity = request.form.get(f'lines[{i}][quantity]', type=float)
                unit_cost = request.form.get(f'lines[{i}][unit_cost]', type=float)
                discount_percent = request.form.get(f'lines[{i}][discount_percent]', type=float, default=0)

                current_app.logger.info(f"Processing line {i}: product_id={product_id}, qty={quantity}, cost={unit_cost}")

                if product_id and quantity and quantity > 0 and unit_cost:
                    product = db.session.get(Product, product_id)

                    if product:
                        line = PurchaseLine(
                            purchase_id=purchase.id,
                            product_id=product_id,
                            quantity=quantity,
                            unit_cost=unit_cost,
                            discount_percent=discount_percent
                        )

                        line.calculate_line_total()
                        db.session.add(line)
                        lines_added += 1
                        current_app.logger.info(f"Line added: {product.name} x {quantity} @ {unit_cost}")

            current_app.logger.info(f"Lines added: {lines_added}")

            if lines_added == 0:
                current_app.logger.warning("No lines added - rolling back")
                db.session.rollback()
                flash('⚠️ يجب إضافة منتج واحد على الأقل للفاتورة.\n💡 اضغط زر "➕ إضافة صف" واختر منتجاً.', 'danger')
                return redirect(url_for('purchases.create'))

            # حساب الإجماليات يدوياً من البيانات المحفوظة
            subtotal = Decimal('0')
            current_app.logger.info(f"Starting calculation for {line_count} lines")

            for i in range(line_count):
                product_id = request.form.get(f'lines[{i}][product_id]', type=int)
                quantity = Decimal(str(request.form.get(f'lines[{i}][quantity]', type=float, default=0)))
                unit_cost = Decimal(str(request.form.get(f'lines[{i}][unit_cost]', type=float, default=0)))
                discount_percent = Decimal(str(request.form.get(f'lines[{i}][discount_percent]', type=float, default=0)))

                current_app.logger.info(f"Line {i}: product_id={product_id}, qty={quantity}, cost={unit_cost}, discount={discount_percent}")

                if product_id and quantity > 0 and unit_cost:
                    line_subtotal = quantity * unit_cost
                    line_discount = line_subtotal * (discount_percent / Decimal('100'))
                    line_total = line_subtotal - line_discount
                    subtotal += line_total
                    current_app.logger.info(f"Line {i} calculated: {line_subtotal} - {line_discount} = {line_total}")
                else:
                    current_app.logger.warning(f"Line {i} skipped: invalid data")

            current_app.logger.info(f"Final subtotal: {subtotal}")

            purchase.subtotal = subtotal
            purchase.tax_amount = subtotal * (Decimal(str(purchase.tax_rate)) / Decimal('100'))
            purchase.total_amount = subtotal + purchase.tax_amount
            purchase.amount_base = purchase.total_amount * purchase.exchange_rate

            current_app.logger.info(f"Final totals: subtotal={purchase.subtotal}, tax={purchase.tax_amount}, total={purchase.total_amount}, aed={purchase.amount_base}")  # noqa: E501

            db.session.flush()

            StockService.process_purchase_lines(purchase, warehouse_id_val)

            # القيود المحاسبية
            GLService.ensure_core_accounts()

            # إعداد قيود اليومية مع فصل الضريبة
            lines = [
                # مدين: المخزون (بالمبلغ قبل الضريبة)
                {'account': '1140', 'debit': purchase.subtotal, 'description': f'شراء بضاعة {purchase.purchase_number}'},
                # دائن: المورد (بالمبلغ الإجمالي)
                {'account': '2110', 'credit': purchase.total_amount, 'description': f'ذمم دائنة - مورد: {purchase.supplier_name}'}
            ]

            # إذا وجدت ضريبة، تضاف كمدين (ضريبة مدخلات / قابلة للاسترداد)
            if purchase.tax_amount > 0:
                # نستخدم حساب الضرائب المستحقة (2130) كحساب وسيط (مدين = لنا، دائن = علينا)
                # أو يمكن استخدام حساب أصول منفصل "ضريبة القيمة المضافة على المدخلات" إذا وجد
                lines.append({
                    'account': '2130',
                    'debit': purchase.tax_amount,
                    'description': f'ضريبة القيمة المضافة (شراء) {purchase.purchase_number}'
                })

            GLService.post_entry(
                lines,
                description=f'Purchase {purchase.purchase_number}',
                reference_type='Purchase',
                reference_id=purchase.id,
                currency=purchase.currency,
                exchange_rate=purchase.exchange_rate
            )

            # تحديث إحصائيات المورد
            if supplier:
                try:
                    supplier.update_statistics()
                except Exception as e:
                    current_app.logger.warning(f'Supplier stats update failed: {e}')

            current_app.logger.info("About to commit to database...")
            current_app.logger.info(f"Final values: subtotal={purchase.subtotal}, tax_amount={purchase.tax_amount}, total_amount={purchase.total_amount}, amount_base={purchase.amount_base}")  # noqa: E501
            db.session.commit()
            current_app.logger.info("Database commit successful!")

            create_audit_log('create', 'purchases', purchase.id)

            flash('✅ تم إنشاء فاتورة الشراء بنجاح!', 'success')
            return redirect(url_for('purchases.view', id=purchase.id))

        except Exception as e:
            current_app.logger.error(f"Error in purchase creation: {str(e)}")
            current_app.logger.error(f"Error type: {type(e)}")
            import traceback
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            db.session.rollback()
            flash(f'❌ حدث خطأ: {str(e)}\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')

    exchange_rates = CurrencyService.get_all_rates('AED')
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(
        Warehouse.is_main.desc(), Warehouse.name
    ).all()

    return render_template('purchases/create.html', exchange_rates=exchange_rates, warehouses=warehouses)


@purchases_bp.route('/<int:id>')
@login_required
@permission_required('manage_purchases')
def view(id):
    purchase = db.get_or_404(Purchase, id)
    return render_template('purchases/view.html', purchase=purchase)


@purchases_bp.route('/<int:id>/print')
@login_required
@permission_required('manage_purchases')
def print_purchase(id):
    purchase = db.get_or_404(Purchase, id)
    from flask import current_app
    company = {
        'name_ar': current_app.config.get('COMPANY_NAME_AR'),
        'address': current_app.config.get('COMPANY_ADDRESS'),
        'phone': current_app.config.get('COMPANY_PHONE'),
    }
    return render_template('purchases/print.html', purchase=purchase, company=company)


@purchases_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_purchases')
def edit(id):
    """تعديل فاتورة شراء - الملاحظات والخصم فقط"""
    purchase = db.get_or_404(Purchase, id)

    # منع التعديل للفواتير المدفوعة
    if purchase.get_paid_amount() > 0:
        flash('⚠️ لا يمكن تعديل فاتورة شراء تم الدفع عليها.\n💡 للحفاظ على السجلات المحاسبية.', 'danger')
        return redirect(url_for('purchases.view', id=id))

    if request.method == 'POST':
        try:
            # تعديل الملاحظات فقط
            purchase.notes = request.form.get('notes', '')

            db.session.commit()
            create_audit_log('update', 'purchases', id)

            flash('✅ تم تحديث فاتورة الشراء بنجاح!', 'success')
            return redirect(url_for('purchases.view', id=id))

        except Exception as e:
            db.session.rollback()
            flash(f'❌ حدث خطأ: {str(e)}\n💡 تحقق من البيانات.', 'danger')

    return render_template('purchases/edit.html', purchase=purchase)


@purchases_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_purchases')
def delete(id):
    """حذف (أرشفة) فاتورة شراء"""
    from services.archive_service import ArchiveService
    from models import Cheque, GLJournalEntry, PurchaseLine
    from services.gl_service import GLService

    purchase = db.get_or_404(Purchase, id)

    # التحقق من الارتباطات
    has_links = False

    # 1. التحقق من المدفوعات (Payments - outgoing linked to this purchase)
    # ملاحظة: المدفوعات للموردين قد لا تكون مرتبطة مباشرة بحقل purchase_id في جدول payments القديم،
    # ولكن إذا كان هناك حقل purchase_id أو عبر supplier_id وتاريخ متزامن،
    # لكن سنفترض وجود علاقة أو استخدام get_paid_amount() كمؤشر
    if purchase.get_paid_amount() > 0:
        has_links = True

    # 2. التحقق من الشيكات (Cheques)
    linked_cheques = Cheque.query.filter_by(purchase_id=purchase.id).count()
    if linked_cheques > 0:
        has_links = True

    try:
        if has_links:
            # أرشفة (Soft Delete)
            # عكس القيد المحاسبي
            if purchase.status != 'cancelled':
                try:
                    GLService.reverse_entry(
                        reference_type='Purchase',
                        reference_id=purchase.id,
                        description=f'Reverse Purchase {purchase.purchase_number} (Archived)'
                    )
                except Exception as e:
                    current_app.logger.error(f'Failed to reverse GL entry for archived purchase {purchase.id}: {e}')

            archive_service = ArchiveService()
            archive_service.archive_record('purchases', purchase, reason='تم أرشفة الفاتورة لوجود مدفوعات أو شيكات', commit=False)

            create_audit_log('archive', 'purchases', id)
            db.session.commit()
            flash(f'✅ تم أرشفة فاتورة الشراء "{purchase.purchase_number}" (لوجود ارتباطات مالية)', 'warning')
        else:
            # حذف نهائي (Hard Delete)
            # 1. حذف البنود (PurchaseLines)
            PurchaseLine.query.filter_by(purchase_id=purchase.id).delete()

            # 2. حذف القيود المحاسبية
            GLJournalEntry.query.filter_by(reference_type='Purchase', reference_id=purchase.id).delete()

            # 3. حذف الفاتورة
            db.session.delete(purchase)
            create_audit_log('delete', 'purchases', id)
            db.session.commit()
            flash(f'✅ تم حذف فاتورة الشراء "{purchase.purchase_number}" نهائياً', 'success')

        return redirect(url_for('purchases.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'❌ حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('purchases.view', id=id))


# =====================================
# API Endpoints - Backend Calculations
# =====================================

@purchases_bp.route('/api/calculate-totals', methods=['POST'])
def api_calculate_purchase_totals():
    """API لحساب إجماليات فاتورة المشتريات - Backend Calculation"""
    try:
        from flask import jsonify

        data = request.get_json(force=True)
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        lines = data.get('lines', [])
        tax_rate = Decimal(str(data.get('tax_rate', 0)))

        # حساب المجموع الفرعي
        subtotal = Decimal('0')
        for line in lines:
            try:
                qty = Decimal(str(line.get('quantity', 0)))
                cost = Decimal(str(line.get('unit_cost', 0)))
                discount_percent = Decimal(str(line.get('discount_percent', 0)))

                if qty > 0 and cost > 0:
                    line_subtotal = qty * cost
                    line_discount = line_subtotal * (discount_percent / Decimal('100'))
                    line_total = line_subtotal - line_discount
                    subtotal += line_total
            except (ValueError, TypeError, KeyError):
                continue

        # حساب الضريبة والإجمالي
        tax_amount = subtotal * (tax_rate / Decimal('100'))
        total = subtotal + tax_amount

        return jsonify({
            'success': True,
            'subtotal': float(subtotal),
            'tax_rate': float(tax_rate),
            'tax_amount': float(tax_amount),
            'total': float(total),
            'line_count': len([ln for ln in lines if Decimal(str(ln.get('quantity', 0))) > 0])
        }), 200

    except Exception as e:
        current_app.logger.error(f'Error in calculate_purchase_totals: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500
