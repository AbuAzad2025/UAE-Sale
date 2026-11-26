"""Restore missing journals for one tenant from an operator-verified export."""

import argparse
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select


def restore_journals(tenant_id, actor_id, export):
    from extensions import db
    from models import GLJournalEntry, Tenant, User
    from models.tenant_scope import run_in_tenant_context
    from services.gl_service import GLService
    from utils.transaction import atomic_transaction

    if (
        type(tenant_id) is not int
        or tenant_id <= 0
        or type(export.get("tenant_id")) is not int
        or export["tenant_id"] != tenant_id
    ):
        raise ValueError("The export must belong to the explicitly selected tenant.")

    def restore():
        with atomic_transaction():
            if db.session.get(Tenant, tenant_id) is None:
                raise ValueError("The selected tenant does not exist.")
            actor = db.session.scalar(
                select(User)
                .where(User.id == actor_id)
                .execution_options(skip_tenant_filter=True)
            )
            if (
                actor is None
                or not actor.is_active
                or not (
                    actor.is_owner
                    or (
                        actor.tenant_id == tenant_id
                        and actor.has_permission("manage_ledger")
                    )
                )
            ):
                raise ValueError(
                    "The actor must be authorized to manage this tenant's ledger."
                )

            restored = 0
            seen = set()
            for record in export["journals"]:
                if record.get("tenant_id", tenant_id) != tenant_id:
                    raise ValueError(
                        "The export includes a journal from a different tenant."
                    )
                source = record["entry_number"]
                if (
                    not isinstance(source, str)
                    or not source.strip()
                    or len(source) > 100
                ):
                    raise ValueError(
                        "Each recovery journal needs its original entry number."
                    )
                if source in seen:
                    raise ValueError(
                        f"Duplicate entry in the supplied export: {source}"
                    )
                seen.add(source)
                key = f"rebuild:{source}"
                if (
                    GLJournalEntry.query.filter_by(
                        tenant_id=tenant_id, idempotency_key=key
                    ).first()
                    is not None
                ):
                    continue
                existing = GLJournalEntry.query.filter_by(
                    tenant_id=tenant_id, entry_number=source
                ).one_or_none()
                if existing is not None and not (
                    existing.idempotency_key or ""
                ).startswith("rebuild:"):
                    continue
                GLService.post_entry(
                    lines=record["lines"],
                    description=record["description"],
                    reference_type=record.get("reference_type"),
                    reference_id=record.get("reference_id"),
                    currency=record["currency"],
                    exchange_rate=record["exchange_rate"],
                    entry_type=record.get("entry_type", "manual"),
                    entry_date=date.fromisoformat(record["entry_date"]),
                    notes=f"Restored from verified export, original journal {source}",
                    created_by=actor_id,
                    tenant_id=tenant_id,
                    idempotency_key=key,
                )
                restored += 1
            return restored

    return run_in_tenant_context(tenant_id, restore)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=int)
    parser.add_argument("--actor-id", required=True, type=int)
    parser.add_argument(
        "--journal-file",
        required=True,
        type=Path,
        help="Verified JSON containing tenant_id and journals with original entry number, date, currency, rate and account-code lines.",
    )
    args = parser.parse_args(argv)
    if args.tenant_id <= 0 or args.actor_id <= 0:
        parser.error("Tenant and actor IDs must be positive.")
    export = json.loads(
        args.journal_file.read_text(encoding="utf-8"), parse_float=Decimal
    )

    os.environ["ENABLE_SCHEDULERS"] = "0"
    from app import create_app

    with create_app(run_startup_tasks=False).app_context():
        count = restore_journals(args.tenant_id, args.actor_id, export)
    print(f"Restored {count} journal(s) for tenant {args.tenant_id}.")


if __name__ == "__main__":
    main()
