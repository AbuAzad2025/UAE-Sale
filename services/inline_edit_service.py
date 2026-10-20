"""Inline editing: the single-field update behind /api/inline-edit/<type>/<id>.

static/js/azad-app.js turns a cell into an input and PATCHes the new value:
    fetch('/api/inline-edit/' + entityType + '/' + entityId, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({field: field, value: newValue})
    })

The route did not exist, so every inline edit 404'd.

Security notes, because this endpoint writes to a row by request:

* Only a FIXED allowlist of fields per entity type may be written. A generic
  "update any column" endpoint would let a caller set is_active, is_owner,
  tenant_id, cost_price or a balance - so the allowlist is the security
  boundary, not a convenience.
* The row is resolved with get_owned_or_404, so a row belonging to another
  tenant is refused exactly like everywhere else.
* Permission is checked per entity type, matching the permission each
  module's own routes require.
* The value is coerced to the column's type, so a string cannot be written
  into a numeric column and break later arithmetic.
"""
from decimal import Decimal, InvalidOperation

from flask import jsonify, request
from flask_login import current_user

from extensions import db
from utils.decorators import get_owned_or_404

# entity type -> (model, editable fields, required permission)
#
# The field lists are deliberately short: they cover the values a user
# reasonably wants to correct in place, and nothing else.
INLINE_EDITABLE = {
    'customer': {
        'model': 'Customer',
        'permission': 'manage_customers',
        'fields': {
            'name': 'text',
            'name_ar': 'text',
            'phone': 'text',
            'email': 'text',
            'address': 'text',
            'notes': 'text',
        },
    },
    'supplier': {
        'model': 'Supplier',
        'permission': 'manage_suppliers',
        'fields': {
            'name': 'text',
            'name_ar': 'text',
            'company_name': 'text',
            'phone': 'text',
            'phone2': 'text',
            'email': 'text',
            'website': 'text',
            'address': 'text',
            'city': 'text',
            'notes': 'text',
        },
    },
    'product': {
        'model': 'Product',
        'permission': 'manage_products',
        'fields': {
            'name': 'text',
            'name_ar': 'text',
            'commercial_name': 'text',
            'sku': 'text',
            'part_number': 'text',
            'barcode': 'text',
            'location': 'text',
            'unit': 'text',
            'regular_price': 'decimal',
            'merchant_price': 'decimal',
            'partner_price': 'decimal',
            'min_stock_alert': 'decimal',
        },
    },
    'sale': {
        'model': 'Sale',
        'permission': 'manage_sales',
        'fields': {
            'notes': 'text',
        },
    },
    'purchase': {
        'model': 'Purchase',
        'permission': 'manage_purchases',
        'fields': {
            'notes': 'text',
            'supplier_name': 'text',
        },
    },
}


def _resolve_model(name):
    from models import (Customer, Product, Purchase, Sale, Supplier)
    return {
        'Customer': Customer,
        'Supplier': Supplier,
        'Product': Product,
        'Sale': Sale,
        'Purchase': Purchase,
    }.get(name)


def _coerce(kind, value):
    """حوّل القيمة إلى نوع العمود، أو ارفع خطأ واضح.

    Without this a string can be written into a numeric column, which breaks
    arithmetic further down the line.
    """
    if value is None:
        return None
    text = str(value).strip()
    if kind == 'text':
        return text if text else None
    if kind == 'decimal':
        if text == '':
            return None
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            raise ValueError(f'قيمة رقمية غير صالحة: {text!r}')
    return value


def inline_edit(entity_type, entity_id):
    """PATCH /api/inline-edit/<entity_type>/<entity_id>

    Body: {"field": "<name>", "value": <value>}
    """
    spec = INLINE_EDITABLE.get((entity_type or '').lower())
    if spec is None:
        return jsonify({
            'success': False,
            'error': 'نوع كيان غير مدعوم',
            'allowed': sorted(INLINE_EDITABLE),
        }), 400

    if not current_user.has_permission(spec['permission']):
        return jsonify({
            'success': False,
            'error': 'لا تملك صلاحية تعديل هذا السجل',
            'code': 'PERMISSION_DENIED',
        }), 403

    data = request.get_json(silent=True) or {}
    field = data.get('field')
    if field not in spec['fields']:
        return jsonify({
            'success': False,
            'error': 'حقل غير قابل للتعديل',
            'code': 'FIELD_NOT_EDITABLE',
            'allowed': sorted(spec['fields']),
        }), 400

    model = _resolve_model(spec['model'])
    if model is None:
        return jsonify({
            'success': False,
            'error': 'تعذر تحميل النموذج',
        }), 500

    # get_owned_or_404 enforces the tenant boundary: a row of another tenant
    # answers 404, never 200.
    obj = get_owned_or_404(model, entity_id, code=404)
    if obj is None:
        return jsonify({
            'success': False,
            'error': 'السجل غير موجود',
            'code': 'NOT_FOUND',
        }), 404

    try:
        coerced = _coerce(spec['fields'][field], data.get('value'))
    except ValueError as exc:
        return jsonify({
            'success': False,
            'error': str(exc),
            'code': 'INVALID_VALUE',
        }), 400

    old_value = getattr(obj, field, None)
    setattr(obj, field, coerced)
    db.session.commit()

    return jsonify({
        'success': True,
        'id': obj.id,
        'field': field,
        'value': coerced,
        'old_value': old_value,
    })
