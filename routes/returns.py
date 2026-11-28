from flask import Blueprint, request, jsonify, render_template, current_app
from flask_login import login_required, current_user
from services.return_service import ReturnService
from models import ProductReturn, Sale
from extensions import db
from utils.decorators import permission_required
from utils.decorators import get_owned_or_404
from utils.transaction import atomic_transaction

returns_bp = Blueprint("returns", __name__, url_prefix="/returns")


@returns_bp.route("/api/create", methods=["POST"])
@login_required
@permission_required("manage_sales")
def api_create_return():
    """
    API Endpoint to create a sales return.
    Expects JSON data:
    {
        "sale_id": int,
        "notes": str,
        "lines": [
            {
                "sale_line_id": int,
                "quantity": float,
                "condition": str,
                "notes": str
            }
        ]
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400

        sale_id = data.get("sale_id")
        lines = data.get("lines", [])
        notes = data.get("notes")

        if not sale_id or not lines:
            return jsonify(
                {"success": False, "message": "Missing sale_id or lines"}
            ), 400

        with atomic_transaction():
            result = ReturnService.create_return(
                sale_id=sale_id,
                return_lines_data=lines,
                user_id=current_user.id,
                notes=notes,
            )

        return jsonify(
            {
                "success": True,
                "message": "Return processed successfully",
                "return_id": result.id,
                "return_number": result.return_number,
            }
        )

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error creating return: {e}")
        return jsonify({"success": False, "message": "Internal server error"}), 500


@returns_bp.route("/api/<int:id>/approve", methods=["POST"])
@login_required
@permission_required("manage_sales")
def api_approve_return(id):
    """Approve a pending sales return (HTTP counterpart of the service call).

    Returns stay ``pending`` until this endpoint is called; the service owns
    the balance/settlement recomputation, so no formula is duplicated here.
    """
    product_return = get_owned_or_404(ProductReturn, id)
    if product_return.sale_id:
        get_owned_or_404(Sale, product_return.sale_id)
    try:
        data = request.get_json(silent=True) or {}
        notes = data.get("notes")
        with atomic_transaction():
            result = ReturnService.approve_return(
                id, user_id=current_user.id, notes=notes
            )
        return jsonify(
            {
                "success": True,
                "message": "Return approved successfully",
                "return_id": result.id,
                "return_number": result.return_number,
                "status": result.status,
            }
        )
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error approving return {id}: {e}")
        return jsonify({"success": False, "message": "Internal server error"}), 500


@returns_bp.route("/view/<int:id>")
@login_required
@permission_required("manage_sales")
def view(id):
    product_return = get_owned_or_404(ProductReturn, id)
    get_owned_or_404(Sale, product_return.sale_id)
    return render_template("returns/view.html", product_return=product_return)
