"""Post opening-stock movements to the GL exactly once.

Products created with an initial stock record a StockMovement with
reference_type='Product Creation' but no journal entry, so the physical stock
valuation exceeds the Inventory account. This service posts a balanced entry
for every such movement that has not been posted yet:

    Dr 1140 Inventory       (quantity x unit cost at creation)
    Cr 3100 Capital         opening stock equity

Idempotency: the journal entry's reference_type/reference_id point at the
stock movement, so reposting skips movements that already have an entry.
"""

from decimal import Decimal, ROUND_HALF_UP

from extensions import db
from models import GLJournalEntry, StockMovement
from services.gl_service import GLService

MONEY = Decimal("0.001")
INVENTORY_CODE = "1140"
EQUITY_CODE = "3100"
OPENING_REF_TYPE = "OpeningStock"
SOURCE_REF_TYPE = "Product Creation"


class OpeningStockService:
    @staticmethod
    def pending(tenant_id=None):
        q = StockMovement.query.filter_by(reference_type=SOURCE_REF_TYPE)
        if tenant_id is not None:
            q = q.filter_by(tenant_id=tenant_id)
        rows = q.order_by(StockMovement.id).all()
        posted = {
            rid for (rid,) in db.session.query(GLJournalEntry.reference_id)
            .filter(GLJournalEntry.reference_type == OPENING_REF_TYPE)
            .all()
        }
        return [r for r in rows if r.id not in posted]

    @staticmethod
    def post_one(movement, actor=None):
        """Post one movement. Returns the journal entry or None if duplicate."""
        duplicate = GLJournalEntry.query.filter_by(
            reference_type=OPENING_REF_TYPE, reference_id=movement.id
        ).first()
        if duplicate is not None:
            return None

        product = movement.product
        unit_cost = Decimal(str(getattr(product, "cost_price", 0) or 0))
        qty = Decimal(str(movement.quantity or 0))
        amount = (qty * unit_cost).quantize(MONEY, rounding=ROUND_HALF_UP)
        if amount <= 0:
            return None

        GLService.ensure_core_accounts()
        entry = GLService.post_entry(
            [
                {"account": INVENTORY_CODE, "debit": amount,
                 "description": f"رصيد افتتاحي مخزون - {product.name}"},
                {"account": EQUITY_CODE, "credit": amount,
                 "description": f"رصيد افتتاحي مخزون - {product.name}"},
            ],
            description=f"Opening stock {movement.id}",
            reference_type=OPENING_REF_TYPE,
            reference_id=movement.id,
            currency="ILS",
            exchange_rate=Decimal("1"),
        )
        return entry

    @staticmethod
    def post_all(tenant_id=None, actor=None):
        entries = []
        for movement in OpeningStockService.pending(tenant_id):
            entry = OpeningStockService.post_one(movement, actor)
            if entry is not None:
                entries.append(entry)
        return entries
