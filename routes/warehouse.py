from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    current_app,
)
from flask_login import login_required, current_user
from extensions import db
from models import Product, StockMovement, Warehouse
from services.stock_service import StockService
from utils.decorators import permission_required, get_owned_or_404

from decimal import Decimal, InvalidOperation
from werkzeug.exceptions import HTTPException

warehouse_bp = Blueprint("warehouse", __name__, url_prefix="/warehouse")


def low_stock_sql():
    """Single low-stock predicate for product queries (NULLs count as zero).

    Mirrors StockService.get_low_stock_products() so the filtered list and the
    low-stock report agree on which products are low.
    """
    from sqlalchemy import func

    return func.coalesce(Product.current_stock, 0) <= func.coalesce(
        Product.min_stock_alert, 0
    )


def is_low_stock(product):
    """In-memory counterpart of :func:`low_stock_sql` used for the stats row."""
    return (product.current_stock or 0) <= (product.min_stock_alert or 0)


@warehouse_bp.route("/api/upload_product_image", methods=["POST"])
@login_required
@permission_required("manage_products")
def upload_product_image():
    """رفع صورة منتج مع تصغيرها وإنشاء مصغّرة.

    static/js/shop.js ينادي هذا المسار، ولم يكن موجوداً فكان رفع صورة
    المنتج يعيد 404.

    الملف يمرّ على utils.helpers.save_uploaded_file (قائمة امتدادات،
    حد حجم، فحص polyglot) ثم تُفتح فعلياً بـPillow - وهذا ما يثبت أنها
    صورة فعلاً لا ملفاً بامتداد صورة.
    """
    from services.image_service import ImageProcessingError, process_and_store

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(
            {
                "ok": False,
                "error": "لم يتم إرفاق ملف",
            }
        ), 400

    subdir = (request.form.get("subdir") or "products").strip().strip("/")
    if subdir not in ("products", "product-images"):
        return jsonify(
            {
                "ok": False,
                "error": "مجلد غير مسموح",
            }
        ), 400

    try:
        url, thumb_url = process_and_store(
            file,
            subdir=subdir,
            max_side=request.form.get("max_side", 1200),
            quality=request.form.get("quality", 82),
        )
    except ImageProcessingError as exc:
        current_app.logger.warning("Product image rejected: %s", exc)
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 400
    except ValueError as exc:
        current_app.logger.warning("Product image rejected: %s", exc)
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 400

    return jsonify(
        {
            "ok": True,
            "url": url,
            "thumb_url": thumb_url,
        }
    )


@warehouse_bp.route("/")
@login_required
@permission_required("manage_warehouse")
def index():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    search = request.args.get("search", "", type=str)
    category_id = request.args.get("category", type=int)
    stock_filter = request.args.get("stock", "", type=str)

    query = Product.query.filter_by(is_active=True)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            db.or_(
                Product.name.ilike(search_filter),
                Product.sku.ilike(search_filter),
                Product.barcode.ilike(search_filter),
            )
        )

    if category_id:
        query = query.filter_by(category_id=category_id)

    if stock_filter == "low":
        query = query.filter(low_stock_sql())
    elif stock_filter == "out":
        query = query.filter(Product.current_stock <= 0)

    pagination = query.order_by(Product.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Stock health stats over ALL active products (not just this page).
    all_products = Product.query.filter_by(is_active=True).all()
    total_products = len(all_products)
    out_count = sum(1 for p in all_products if (p.current_stock or 0) <= 0)
    low_count = sum(
        1 for p in all_products if (p.current_stock or 0) > 0 and is_low_stock(p)
    )
    good_count = total_products - out_count - low_count

    return render_template(
        "warehouse/index.html",
        products=pagination.items,
        pagination=pagination,
        total_products=total_products,
        good_count=good_count,
        low_count=low_count,
        out_count=out_count,
    )


@warehouse_bp.route("/opening-stock")
@login_required
@permission_required("manage_warehouse")
def opening_stock():
    """Rigid, idempotent posting of opening stock to the GL."""
    from services.opening_stock_service import OpeningStockService

    tid = getattr(current_user, "tenant_id", None)
    rows = OpeningStockService.pending(tid)
    total = sum(
        (Decimal(str(m.quantity or 0)) * Decimal(str(m.product.cost_price or 0)))
        for m in rows
    )
    return render_template(
        "warehouse/opening_stock.html",
        pending=rows,
        total=total,
    )


@warehouse_bp.route("/opening-stock/post", methods=["POST"])
@login_required
@permission_required("manage_warehouse")
def post_opening_stock():
    from services.opening_stock_service import OpeningStockService

    tid = getattr(current_user, "tenant_id", None)
    entries = OpeningStockService.post_all(tid, current_user)
    db.session.commit()
    if entries:
        flash(f"✅ تم ترحيل {len(entries)} حركة رصيد افتتاحي إلى الأستاذ", "success")
    else:
        flash("لا توجد حركات رصيد افتتاحي بانتظار الترحيل.", "info")
    return redirect(url_for("warehouse.opening_stock"))


@warehouse_bp.route("/movements")
@login_required
@permission_required("manage_warehouse")
def movements():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    product_id = request.args.get("product", type=int)
    movement_type = request.args.get("type", "", type=str)
    warehouse_id = request.args.get("warehouse", type=int)

    query = StockMovement.query

    if product_id:
        query = query.filter_by(product_id=product_id)

    if movement_type:
        query = query.filter_by(movement_type=movement_type)

    if warehouse_id:
        query = query.filter_by(warehouse_id=warehouse_id)
        current_warehouse = get_owned_or_404(Warehouse, warehouse_id, code=404)
    else:
        current_warehouse = None

    pagination = query.order_by(StockMovement.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    warehouses = (
        Warehouse.query.filter_by(is_active=True).order_by(Warehouse.name).all()
    )

    return render_template(
        "warehouse/movements.html",
        movements=pagination.items,
        pagination=pagination,
        warehouses=warehouses,
        current_warehouse=current_warehouse,
    )


@warehouse_bp.route("/low-stock")
@login_required
@permission_required("manage_warehouse")
def low_stock():
    products = StockService.get_low_stock_products()
    return render_template("warehouse/low_stock.html", products=products)


@warehouse_bp.route("/out-of-stock")
@login_required
@permission_required("manage_warehouse")
def out_of_stock():
    products = StockService.get_out_of_stock_products()
    return render_template("warehouse/out_of_stock.html", products=products)


@warehouse_bp.route("/<int:id>")
@login_required
@permission_required("manage_warehouse")
def view_warehouse(id):
    warehouse = get_owned_or_404(Warehouse, id, code=404)

    stock_query = (
        db.session.query(
            StockMovement.product_id,
            db.func.sum(StockMovement.quantity).label("total_quantity"),
        )
        .filter_by(warehouse_id=id)
        .group_by(StockMovement.product_id)
        .all()
    )

    warehouse_stock = []
    for product_id, quantity in stock_query:
        qty = float(quantity) if quantity is not None else 0.0
        if qty != 0:
            product = get_owned_or_404(Product, product_id)
            if product:
                warehouse_stock.append({"product": product, "quantity": qty})

    return render_template(
        "warehouse/view_warehouse.html", warehouse=warehouse, stock=warehouse_stock
    )


@warehouse_bp.route("/create", methods=["GET", "POST"])
@warehouse_bp.route("/create-warehouse", methods=["GET", "POST"])
@login_required
@permission_required("manage_warehouse")
def create_warehouse():  # noqa: C901
    from models import User

    parent_warehouses = Warehouse.query.filter_by(is_active=True, parent_id=None).all()
    users = User.query.filter_by(is_active=True, is_owner=False).all()

    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            name_ar = request.form.get("name_ar", "").strip()
            code = request.form.get("code", "").strip()
            location = request.form.get("location", "").strip()
            parent_id = request.form.get("parent_id", type=int) or None
            manager_id = request.form.get("manager_id", type=int) or None
            is_main = request.form.get("is_main") == "on"

            if not name:
                flash("اسم المستودع مطلوب", "warning")
                return render_template(
                    "warehouse/create_warehouse.html",
                    parent_warehouses=parent_warehouses,
                    users=users,
                    form_data=request.form,
                )

            if not location:
                flash("الموقع مطلوب", "warning")
                return render_template(
                    "warehouse/create_warehouse.html",
                    parent_warehouses=parent_warehouses,
                    users=users,
                    form_data=request.form,
                )

            if code:
                existing = Warehouse.query.filter_by(code=code).first()
                if existing:
                    flash("رمز المستودع موجود مسبقاً", "warning")
                    return render_template(
                        "warehouse/create_warehouse.html",
                        parent_warehouses=parent_warehouses,
                        users=users,
                        form_data=request.form,
                    )

            if parent_id:
                parent_warehouse = get_owned_or_404(Warehouse, parent_id, code=404)
                if not parent_warehouse.is_active:
                    flash("المستودع الأب غير نشط", "warning")
                    return render_template(
                        "warehouse/create_warehouse.html",
                        parent_warehouses=parent_warehouses,
                        users=users,
                        form_data=request.form,
                    )

            warehouse = Warehouse(
                name=name,
                name_ar=name_ar,
                code=code,
                location=location,
                parent_id=parent_id,
                is_main=is_main,
                manager_id=manager_id,
                is_active=True,
            )

            db.session.add(warehouse)
            db.session.commit()

            warehouse_type = "فرعي" if parent_id else "مستقل"
            flash(f'✓ تم إنشاء المستودع {warehouse_type} "{name}" بنجاح', "success")
            return redirect(url_for("warehouse.list_warehouses"))

        except Exception:
            db.session.rollback()
            current_app.logger.exception("handler failed")
            flash("خطأ في إنشاء المستودع: حدث خطأ غير متوقع", "error")
            return render_template(
                "warehouse/create_warehouse.html",
                parent_warehouses=parent_warehouses,
                users=users,
                form_data=request.form,
            )

    return render_template(
        "warehouse/create_warehouse.html",
        parent_warehouses=parent_warehouses,
        users=users,
    )


@warehouse_bp.route("/list")
@login_required
@permission_required("manage_warehouse")
def list_warehouses():
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    return render_template("warehouse/list_warehouses.html", warehouses=warehouses)


@warehouse_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_warehouse")
def delete_warehouse(id):
    """حذف مستودع"""
    warehouse = get_owned_or_404(Warehouse, id, code=404)

    if warehouse.is_main:
        flash("لا يمكن حذف المستودع الرئيسي", "danger")
        return redirect(url_for("warehouse.list_warehouses"))

    try:
        has_stock = StockMovement.query.filter_by(warehouse_id=id).first()
        if has_stock:
            warehouse.is_active = False
            db.session.commit()
            flash(
                f'تم إلغاء تفعيل المستودع "{warehouse.name}" لوجود حركات مخزنية مرتبطة به',
                "warning",
            )
        else:
            db.session.delete(warehouse)
            db.session.commit()
            flash(f'تم حذف المستودع "{warehouse.name}" بنجاح', "success")

    except Exception:
        db.session.rollback()
        current_app.logger.exception("handler failed")
        flash("فشل الحذف: حدث خطأ غير متوقع", "danger")

    return redirect(url_for("warehouse.list_warehouses"))


@warehouse_bp.route("/add-stock/<int:product_id>", methods=["POST"])
@login_required
@permission_required("manage_warehouse")
def add_stock(product_id):
    try:
        product = get_owned_or_404(Product, product_id)
        quantity = Decimal(request.form.get("quantity", 0))
        notes = request.form.get("notes", "").strip()
        warehouse_id = request.form.get("warehouse_id", type=int)

        if not quantity.is_finite() or quantity <= 0:
            return jsonify(
                {"success": False, "message": "الكمية يجب أن تكون أكبر من صفر"}
            ), 400

        if not warehouse_id:
            warehouse = Warehouse.query.filter_by(is_active=True, is_main=True).first()
            if not warehouse:
                warehouse = Warehouse.query.filter_by(is_active=True).first()
            if not warehouse:
                return jsonify({"success": False, "message": "لا يوجد مستودع نشط"}), 400
            warehouse_id = warehouse.id

        StockService.adjust_stock(
            product_id,
            quantity,
            warehouse_id=warehouse_id,
            notes=notes or "إضافة كمية يدوية",
            reference_type="Manual Adjustment",
            require_valuation=True,
        )
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f"تم إضافة {quantity} وحدة للمنتج {product.name}",
                "new_stock": float(product.current_stock),
            }
        )

    except HTTPException:
        raise
    except (InvalidOperation, ValueError) as e:
        db.session.rollback()
        message = str(e) if isinstance(e, ValueError) else "الكمية غير صالحة."
        return jsonify({"success": False, "message": message}), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to add stock and post its valuation")
        return jsonify({"success": False, "message": "تعذّر إضافة المخزون."}), 500
