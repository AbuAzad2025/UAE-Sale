"""Standalone worker for bot_events. Uses the ERP database as its only broker."""

from argparse import ArgumentParser
from pathlib import Path
from signal import SIGINT, SIGTERM, signal
from time import monotonic, sleep

from flask import Flask, current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from bot_core.agent import AgentRunner, ToolCall
from bot_core.agent.deadline import sql_deadline
from bot_core.agent.erp import build_registry
from bot_core.context import capture, forget, remember
from bot_core.dialogue import Dialogue, StateManager
from bot_core.dialogue.routing import Decision, decide, from_prediction
from bot_core.gateway.store import Claim, claim_next, finish
from bot_core.neural_nlu.budget import BoundedInference, Interpreter
from bot_core.neural_nlu.artifacts import RELEASE_MODEL, verify_release_model
from bot_core.neural_nlu.retrieval import guide
from bot_core.observability import utcnow
from bot_core.security import Actor, Effect, authorize
from extensions import db
from models import Tenant, User
from models.tenant_scope import clear_current_tenant_id, set_current_tenant_id
from services.assistant_imports import ImportValidationError
from services.assistant_purchases import PurchaseValidationError
from services.assistant_quotes import QuoteValidationError
from services.assistant_transfers import TransferValidationError


def _principal(actor: Actor) -> User:
    # Platform administrators can select a company in the authenticated web session.
    user = db.session.get(User, actor.user_id, execution_options={"skip_tenant_filter": True})
    if user is None or not user.is_active:
        raise PermissionError("The ERP user is unavailable.")
    if not user.is_owner and (
        actor.tenant_id is None or (user.tenant_id != actor.tenant_id and not user.is_super_admin())
    ):
        raise PermissionError("The ERP company scope changed.")
    if actor.tenant_id is not None:
        company = db.session.get(Tenant, actor.tenant_id)
        if company is None or not company.is_active:
            raise PermissionError("The ERP company is unavailable.")
    return user


def process(
    claim: Claim, runner: AgentRunner, states: StateManager, nlu: Interpreter | None = None,
) -> None:
    actor = claim.event.actor
    command = claim.event.command
    started = monotonic()
    started_at = utcnow()
    trace = {"intent": None, "confidence": 0.0, "entities": {}, "tools": []}
    try:
        user = _principal(actor)
        set_current_tenant_id(actor.tenant_id)
        prior = states.load(actor)
        context = capture(actor, user, prior)
        if command is not None:
            name = command["tool"]
            if name not in ("confirm_action", "prepare_stock_import"):
                raise ValueError("Unsupported authenticated command.")
            decision = Decision(name, ToolCall(name, command["arguments"]), "")
        else:
            decision = decide(claim.event, prior)
        threshold = current_app.config.get("BOT_NLU_CONFIDENCE", 0.85)
        if not 0 < threshold <= 1:
            threshold = 0.85
        wants_guide = claim.event.normalized.startswith(("كيف ", "how ", "help ", "دليل "))
        if decision.tool is None and not decision.reset and decision.dialogue is None and nlu is not None:
            try:
                prediction = nlu.predict(claim.event.raw_input)
                trace["predicted_intent"] = prediction.intent
                trace["extracted_entities"] = prediction.entities
                decision = from_prediction(prediction, threshold, decision, message=claim.event.raw_input)
                wants_guide = wants_guide or (prediction.intent == "guide" and prediction.confidence >= threshold)
            except TimeoutError:
                trace["inference"] = "timeout"
            except Exception:
                current_app.logger.warning("Local bot inference failed; using deterministic guidance", exc_info=True)
        trace["intent"] = decision.tool or ("reset" if decision.reset else "clarification")
        trace["confidence"] = decision.confidence
        if decision.tool:
            authorize(actor, user, runner.registry.get(decision.tool).permissions)
        if decision.call is not None:
            trace["tools"] = [decision.call.name]
            result = runner.run(
                [decision.call], actor, user, claim.event.id,
                confirmed=command is not None and decision.call.name == "confirm_action",
                direct_mutation=decision.direct_mutation,
            )[0]
            trace["entities"] = dict(result.entities)
            if result.outcome in {"read", "confirmed", "proposed", "updated", "ambiguous"}:
                remember(context, decision.call.name, result.entities, ambiguous=result.outcome == "ambiguous")
            if decision.call.name == "confirm_action":
                if prior and prior.topic == "confirmation" and prior.slots["action_id"] == command["arguments"]["action_id"]:
                    states.reset(actor)
            elif prior and prior.topic in {"purchase_order", "stock_transfer", "confirmation"} and (
                runner.registry.get(decision.call.name).effect is Effect.READ or decision.direct_mutation
            ):
                states.save(actor, prior)
            elif result.outcome == "proposed" and result.data:
                states.save(actor, Dialogue("confirmation", {"action_id": str(result.data["action_id"])}))
            elif result.dialogue is not None:
                states.save(actor, result.dialogue)
            elif result.outcome in ("ambiguous", "not_found") and not decision.direct_mutation:
                states.save(actor, Dialogue(decision.call.name, {}))
            else:
                states.reset(actor)
            payload = {"message": result.message, "outcome": result.outcome}
            if result.data:
                payload["data"] = dict(result.data)
        else:
            message = decision.prompt
            if decision.reset:
                forget(actor)
                if states.cancel(actor, prior):
                    message = "أُلغيت خطوة المحادثة والمسودة المعلّقة."
            elif decision.dialogue is not None:
                states.save(actor, decision.dialogue)
            elif decision.tool and (prior is None or prior.topic not in {"purchase_order", "stock_transfer", "confirmation"}):
                states.save(actor, Dialogue(decision.tool, {}))
            payload = {"message": message, "outcome": "reset" if decision.reset else "clarification"}
            if decision.tool is None and wants_guide and not decision.reset and decision.dialogue is None:
                guidance = guide(claim.event.raw_input, is_owner=user.is_owner)
                if guidance:
                    payload = {"message": guidance, "outcome": "guide"}
        status = "completed"
    except PermissionError as error:
        db.session.rollback()
        trace["authorization"] = str(error)
        payload = {"message": "لا تملك صلاحية تنفيذ هذا الطلب ضمن الشركة الحالية.", "outcome": "denied"}
        status = "completed"
    except TimeoutError:
        db.session.rollback()
        payload = {"message": "انتهت مهلة العملية. يمكنك إعادة إرسال الطلب.", "outcome": "timeout"}
        if command and command["tool"] == "confirm_action":
            payload["data"] = {"action_id": command["arguments"]["action_id"]}
        status = "failed"
    except (ImportValidationError, PurchaseValidationError, QuoteValidationError, TransferValidationError) as error:
        db.session.rollback()
        trace["entities"] = error.entities
        payload = {"message": str(error), "outcome": "invalid"}
        status = "completed"
    except ValueError:
        db.session.rollback()
        payload = {"message": "راجع بيانات الطلب وأرسلها مرة أخرى.", "outcome": "invalid"}
        status = "completed"
    except Exception:
        db.session.rollback()
        current_app.logger.exception("ERP agent event failed: %s", claim.event.id)
        payload = {"message": "تعذّر تنفيذ الطلب الآن.", "outcome": "error"}
        status = "failed"
    finally:
        clear_current_tenant_id()

    elapsed_ms = round((monotonic() - started) * 1000)
    queue_wait_ms = max(0, round((started_at - claim.queued_at).total_seconds() * 1000)) if claim.queued_at else 0
    trace.update(
        outcome=payload["outcome"], latency_ms=elapsed_ms, queue_wait_ms=queue_wait_ms,
        operation=trace["tools"][0] if trace["tools"] else "message",
    )
    finish(claim, outcome=status, result=payload, trace=trace)


def work_one(
    app: Flask, runner: AgentRunner, states: StateManager, nlu: Interpreter | None = None,
    *, interactive_only: bool = False,
) -> bool:
    with app.app_context():
        claim = claim_next(interactive_only=interactive_only)
        if claim is None:
            return False
        process(claim, runner, states, nlu)
    return True


def verify_queue_schema(app: Flask) -> None:
    with app.app_context(), db.engine.connect() as connection:
        inspector = inspect(connection)
        required = {"bot_events", "bot_event_audit", "bot_conversations", "bot_context_memory", "assistant_actions"}
        missing = required - set(inspector.get_table_names())
        if missing:
            raise RuntimeError(f"Apply ERP migrations before starting the worker. Missing tables: {', '.join(sorted(missing))}")
        event_columns = {column["name"] for column in inspector.get_columns("bot_events")}
        if not {"lease_token", "lease_until", "command", "command_kind"} <= event_columns:
            raise RuntimeError("Apply the current ERP agent migrations before starting the worker.")
        if connection.dialect.name == "postgresql" and not connection.scalar(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_trigger
                WHERE tgrelid = to_regclass('bot_event_audit') AND tgname = 'bot_event_audit_append_only'
                AND NOT tgisinternal AND tgenabled IN ('O', 'A')
            )
        """)):
            raise RuntimeError("The PostgreSQL bot audit trigger is missing or disabled.")


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--interactive-only", action="store_true", help="Reserve this worker for text messages.")
    parser.add_argument("--check", action="store_true", help="Verify queue schema and local NLU, then exit.")
    parser.add_argument("--require-model", action="store_true", help="Exit if local NLU cannot load.")
    parser.add_argument("--wait-for-schema", type=int, default=0, metavar="SECONDS")
    args = parser.parse_args()
    if not 0 <= args.wait_for_schema <= 600:
        parser.error("--wait-for-schema must be between 0 and 600")
    from app import create_app

    app = create_app(run_startup_tasks=False)
    schema_deadline = monotonic() + args.wait_for_schema
    while True:
        try:
            verify_queue_schema(app)
        except (RuntimeError, OperationalError):
            if monotonic() >= schema_deadline:
                raise
            sleep(max(0, min(5, schema_deadline - monotonic())))
        else:
            break
    runner = AgentRunner(build_registry(), deadline=sql_deadline, budget_ms=90000)
    states = StateManager()
    nlu = None
    model_directory = Path(app.config.get("BOT_NLU_MODEL_DIR") or RELEASE_MODEL).resolve()
    if model_directory == RELEASE_MODEL or (model_directory / "SHA256SUMS").is_file():
        verify_release_model(model_directory)
    if model_directory.is_dir():
        try:
            import torch

            from bot_core.neural_nlu.model import LocalNLU

            torch.set_num_threads(1)
            local_model = LocalNLU(model_directory)
            local_model.predict("invoice status INV-1")
            if not args.check:
                nlu = BoundedInference(local_model)
        except (ImportError, OSError, KeyError, RuntimeError, TypeError, ValueError):
            if args.check or args.require_model:
                raise SystemExit("The configured local NLU could not be loaded and exercised.") from None
            app.logger.exception("Local NLU artifacts could not be loaded; deterministic commands remain available")
        else:
            if args.check:
                print(f"ERP queue schema and local NLU are ready (artifact={model_directory.name}).")
                return
    elif args.check or args.require_model:
        raise SystemExit("The configured local NLU directory is missing.")
    app.logger.info("ERP agent worker ready. Local model loaded: %s (artifact=%s, interactive_only=%s)",
                    nlu is not None, model_directory.name, args.interactive_only)
    stopping = False

    def request_shutdown(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal(SIGTERM, request_shutdown)
    signal(SIGINT, request_shutdown)
    try:
        while not stopping:
            try:
                if not work_one(app, runner, states, nlu, interactive_only=args.interactive_only):
                    sleep(0.25)
            except Exception:
                app.logger.exception("ERP agent could not reach its message queue")
                sleep(1)
    finally:
        if nlu is not None:
            nlu.close()


if __name__ == "__main__":
    main()
