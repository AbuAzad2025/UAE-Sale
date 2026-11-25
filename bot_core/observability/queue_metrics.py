"""Summarize recent ERP agent timings without reading message text."""

from argparse import ArgumentParser
from collections import defaultdict
from datetime import timedelta
from json import dumps
from math import ceil
from os import environ

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select

from bot_core.observability import utcnow
from models.bot_event import BotEvent, BotEventAudit


def _percentiles(values: list[int]) -> dict[str, int | None]:
    if not values:
        return {"p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {"p50": ordered[ceil(len(ordered) * 0.50) - 1],
            "p95": ordered[ceil(len(ordered) * 0.95) - 1], "max": ordered[-1]}


def summarize(rows) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("operation", "legacy")].append(row)
    return {
        operation: {
            "requests": len(entries),
            "timeouts": sum(row.get("outcome") == "timeout" for row in entries),
            "queue_expirations": sum(row.get("outcome") == "queue_expired" for row in entries),
            "errors": sum(row.get("outcome") == "error" for row in entries),
            "clarifications": sum(row.get("outcome") == "clarification" for row in entries),
            "queue_ms": _percentiles([row["queue_wait_ms"] for row in entries if "queue_wait_ms" in row]),
            "execution_ms": _percentiles([row["latency_ms"] for row in entries if "latency_ms" in row]),
        }
        for operation, entries in groups.items()
    }


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    if args.minutes < 1 or not 1 <= args.limit <= 50000:
        parser.error("--minutes must be positive and --limit must be between 1 and 50000")
    load_dotenv()
    url = environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL is required")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url)
    audit = BotEventAudit.__table__.c
    events = BotEvent.__table__.c
    now = utcnow()
    query = (
        select(audit.details)
        .where(audit.outcome.in_(("completed", "failed")), audit.recorded_at >= now - timedelta(minutes=args.minutes))
        .order_by(audit.id.desc()).limit(args.limit)
    )
    backlog = (
        select(events.status, events.command_kind, func.count(), func.min(events.created_at))
        .where(events.status.in_(("queued", "processing")))
        .group_by(events.status, events.command_kind)
        .order_by(events.status, events.command_kind)
    )
    with engine.connect() as connection:
        rows = connection.scalars(query).all()
        pending = [
            {"status": status, "command": command or "message", "count": count,
             "oldest_age_ms": max(0, round((now - oldest).total_seconds() * 1000))}
            for status, command, count, oldest in connection.execute(backlog)
        ]
    print(dumps({"minutes": args.minutes, "sample_limit": args.limit, "sample_size": len(rows),
                 "backlog": pending, "operations": summarize(rows)}, indent=2))


if __name__ == "__main__":
    main()
