"""
Webhook Service - خدمة Webhooks
معالجة webhooks من بوابات الدفع
"""

from datetime import datetime, timezone
from extensions import db
from models import Donation, ProcessedWebhookEvent
from services.notification_service import NotificationService
from sqlalchemy.exc import IntegrityError
from flask import has_app_context
import hmac
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


class WebhookService:
    """خدمة معالجة Webhooks"""

    @staticmethod
    def _event_id(provider, data):
        """Stable, provider-scoped identity for an IPN/event payload."""
        raw = str(data.get("event_id") or data.get("id") or "").strip()
        if not raw:
            # Providers that do not send an event id still give a stable
            # (payment_id, status, order/type) tuple. Hash it so arbitrary
            # remote text never lands in a unique index as-is.
            basis = "|".join(
                str(data.get(key) or "")
                for key in ("payment_id", "payment_status", "order_id", "type")
            )
            raw = hashlib.sha256(basis.encode("utf-8")).hexdigest()
        return f"{provider}:{raw}"[:255]

    @staticmethod
    def _claim_event(provider, data):
        """Claim an event for processing; return False when it is a replay.

        The claim is claimed with a DB UNIQUE key so two workers cannot both
        process the same IPN. Callers MUST settle the claim (commit on success,
        rollback on failure) via ``_settle_claim``.
        """
        if not has_app_context():
            # Pure unit tests call the service outside Flask; there is no DB
            # (and no replay window) to protect in that case.
            return True
        event_id = WebhookService._event_id(provider, data)
        try:
            db.session.add(
                ProcessedWebhookEvent(provider=provider, event_id=event_id)
            )
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            logger.info("Ignoring replayed %s webhook event %s", provider, event_id)
            return False
        return True

    @staticmethod
    def _settle_claim(success):
        """Commit a processed event, or release the claim after a failure."""
        if not has_app_context():
            return
        try:
            if success:
                db.session.commit()
            else:
                db.session.rollback()
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def _duplicate_response(provider, data):
        return {
            "success": True,
            "message": "Event already processed",
            "duplicate": True,
            "event_id": WebhookService._event_id(provider, data),
        }

    @staticmethod
    def verify_ipn_signature(raw_body, received_sig, secret):
        """C2 canonical NOWPayments IPN verification (contract C2).

        Canonical scheme: SHA256-HMAC hex digest over the sorted-keys JSON
        serialization of the parsed body:

            expected = HMAC_SHA256(secret, json.dumps(parsed, sort_keys=True))

        Args:
            raw_body: raw request body bytes (or an already-parsed dict)
            received_sig: signature hex string from the request header
            secret: IPN secret

        Returns:
            bool: True only when the canonical signature matches; fails closed.
        """
        if not secret or not received_sig or raw_body is None:
            return False
        try:
            if isinstance(raw_body, (bytes, bytearray)):
                payload = json.loads(raw_body.decode("utf-8"))
            else:
                payload = raw_body
            canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
            expected_signature = hmac.new(
                secret.encode("utf-8"),
                canonical,
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_signature, str(received_sig))
        except Exception:
            return False

    @staticmethod
    def verify_nowpayments_signature(payload, signature, ipn_secret):
        """
        التحقق من توقيع NOWPayments — LEGACY scheme: SHA512-hex-of-raw-body.

        Args:
            payload (bytes): محتوى الـ webhook
            signature (str): التوقيع من header
            ipn_secret (str): IPN Secret

        Returns:
            bool: صحة التوقيع
        """
        if not ipn_secret or payload is None:
            logger.warning("NOWPayments IPN secret not configured")
            return False

        if not isinstance(signature, str) or not signature:
            logger.warning("NOWPayments signature missing or not a string")
            return False

        try:
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            expected_signature = hmac.new(
                ipn_secret.encode("utf-8"), payload, hashlib.sha512
            ).hexdigest()
        except Exception:
            return False

        try:
            return hmac.compare_digest(expected_signature, signature)
        except Exception:
            return False

    @staticmethod
    def process_nowpayments_webhook(
        data, raw_body=None, received_sig=None, ipn_secret=None
    ):  # noqa: C901
        """
        معالجة webhook من NOWPayments

        Signature policy (C2): when both received_sig and ipn_secret are
        provided the webhook must verify under EITHER the canonical
        verify_ipn_signature scheme OR the legacy x-nowpayments-signature
        SHA512-of-body scheme; the matched scheme is logged. If neither
        matches the payload is rejected without processing.

        Args:
            data (dict): بيانات الـ webhook
            raw_body (bytes|None): original request body (used for legacy check)
            received_sig (str|None): signature header value
            ipn_secret (str|None): configured IPN secret

        Returns:
            dict: نتيجة المعالجة
        """
        try:
            if received_sig is not None and ipn_secret:
                body_bytes = raw_body
                if body_bytes is None:
                    try:
                        body_bytes = json.dumps(data).encode("utf-8")
                    except Exception:
                        body_bytes = b""

                canonical_ok = WebhookService.verify_ipn_signature(
                    raw_body if raw_body is not None else data,
                    received_sig,
                    ipn_secret,
                )
                legacy_ok = WebhookService.verify_nowpayments_signature(
                    body_bytes,
                    str(received_sig),
                    ipn_secret,
                )

                if canonical_ok:
                    logger.info(
                        "NOWPayments webhook signature verified via canonical SHA256-sorted-JSON scheme"
                    )
                elif legacy_ok:
                    logger.info(
                        "NOWPayments webhook signature verified via legacy SHA512(body) scheme"
                    )
                else:
                    logger.warning(
                        "NOWPayments webhook signature invalid under all known schemes"
                    )
                    return {"success": False, "error": "Invalid signature"}

            if not WebhookService._claim_event("nowpayments", data):
                return WebhookService._duplicate_response("nowpayments", data)

            payment_id = data.get("payment_id")
            payment_status = data.get("payment_status")
            order_id = data.get("order_id", "")

            logger.info(
                f"📨 NOWPayments webhook received: {payment_id} - {payment_status}"
            )

            if order_id.startswith("DONATION_"):
                result = WebhookService._process_donation_webhook(data)
            else:
                logger.warning(f"Unknown order type: {order_id}")
                result = {"success": False, "error": "Unknown order type"}
            WebhookService._settle_claim(bool(result.get("success")))
            return result

        except Exception as e:
            WebhookService._settle_claim(False)
            logger.error(f"❌ Webhook processing error: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _process_donation_webhook(data):
        """معالجة webhook للتبرعات"""
        payment_status = data.get("payment_status")
        payment_id = data.get("payment_id")

        donation = Donation.query.filter_by(transaction_hash=payment_id).first()

        if not donation:
            logger.warning(f"Donation not found for payment_id: {payment_id}")
            return {"success": False, "error": "Donation not found"}

        if payment_status == "finished":
            donation.status = "completed"
            donation.completed_at = datetime.now(timezone.utc)

            NotificationService.notify_payment_received(
                float(donation.amount_usd),
                donation.donor_name or "مجهول",
                donation.payment_method,
            )

            logger.info(f"✅ Donation {donation.id} completed")

        elif payment_status == "failed" or payment_status == "expired":
            donation.status = "failed"
            logger.warning(f"❌ Donation {donation.id} failed")

        db.session.flush()

        return {"success": True, "message": f"Donation updated to {payment_status}"}

    @staticmethod
    def verify_stripe_signature(payload, signature, webhook_secret):
        """
        التحقق من توقيع Stripe

        Args:
            payload (bytes): محتوى الـ webhook
            signature (str): التوقيع من header
            webhook_secret (str): Webhook Secret

        Returns:
            bool: صحة التوقيع
        """
        if not webhook_secret:
            logger.warning("Stripe webhook secret not configured")
            return False

        try:
            import stripe

            stripe.Webhook.construct_event(payload, signature, webhook_secret)
            return True
        except Exception as e:
            logger.error(f"Stripe signature verification failed: {str(e)}")
            return False

    @staticmethod
    def process_stripe_webhook(data):
        """
        معالجة webhook من Stripe

        Args:
            data (dict): بيانات الـ webhook

        Returns:
            dict: نتيجة المعالجة
        """
        try:
            if not WebhookService._claim_event("stripe", data):
                return WebhookService._duplicate_response("stripe", data)

            event_type = data.get("type")
            event_data = data.get("data", {}).get("object", {})

            logger.info(f"📨 Stripe webhook received: {event_type}")

            if event_type == "payment_intent.succeeded":
                result = WebhookService._process_stripe_payment_success(event_data)
            elif event_type == "payment_intent.payment_failed":
                result = WebhookService._process_stripe_payment_failed(event_data)
            else:
                logger.info(f"Unhandled Stripe event: {event_type}")
                result = {"success": True, "message": "Event acknowledged"}
            WebhookService._settle_claim(bool(result.get("success")))
            return result

        except Exception as e:
            WebhookService._settle_claim(False)
            logger.error(f"❌ Stripe webhook processing error: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _process_stripe_payment_success(payment_intent):
        """معالجة دفعة ناجحة من Stripe"""
        amount = payment_intent.get("amount") / 100  # من cents إلى dollars
        customer_email = payment_intent.get("receipt_email")

        logger.info(f"✅ Stripe payment succeeded: ${amount} from {customer_email}")

        NotificationService.notify_payment_received(
            amount, customer_email or "Unknown", "Stripe"
        )

        return {"success": True, "message": "Payment processed"}

    @staticmethod
    def _process_stripe_payment_failed(payment_intent):
        """معالجة دفعة فاشلة من Stripe"""
        customer_email = payment_intent.get("receipt_email")
        error_message = payment_intent.get("last_payment_error", {}).get(
            "message", "Unknown error"
        )

        logger.warning(
            f"❌ Stripe payment failed for {customer_email}: {error_message}"
        )

        NotificationService.notify_security_alert(
            "فشل دفعة Stripe", f"فشلت دفعة من {customer_email}: {error_message}"
        )

        return {"success": True, "message": "Payment failure processed"}
