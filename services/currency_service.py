import time
from decimal import ROUND_HALF_UP, Decimal

from extensions import db

RATE_QUANTUM = Decimal("0.000001")
DISPLAY_MONEY_QUANTUM = Decimal("0.01")
LRM_MARK = "\u200e"

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from forex_python.converter import CurrencyRates

    FOREX_AVAILABLE = True
except ImportError:
    FOREX_AVAILABLE = False


class CurrencyService:
    CACHE_TTL_SECONDS = 300  # 5 دقائق
    _rates_cache = {}
    # Tracks whether the cached rates came from a live provider or the static
    # fallback. The UI needs this to ask for a manual rate when offline.
    _rates_source = {}
    DEFAULT_BASE = (
        "ILS"  # يُستخدم فقط إذا لم تُعرّف عملة قاعدة للشركة/النظام (الافتراضي شيقل)
    )

    @staticmethod
    def get_base_currency():
        """عملة القاعدة الديناميكية: الشركة الحالية > إعدادات النظام > config.

        يتيح بيع النظام لعدة دول: كل شركة (Tenant) تختار عملتها الأساسية
        من صفحة إعدادات المالك، وكل التحويلات والتقارير تتبعها تلقائيًا.
        """
        try:
            from flask import current_app, has_app_context

            if has_app_context():
                try:
                    from models.tenant_scope import get_current_tenant_id

                    tid = get_current_tenant_id()
                    if tid:
                        from models import Tenant

                        t = db.session.get(Tenant, tid)
                        if t and t.default_currency:
                            return t.default_currency
                except Exception:
                    pass
                try:
                    from models.system_settings import SystemSettings

                    s = SystemSettings.query.filter_by(is_active=True).first()
                    if s and s.default_currency:
                        return s.default_currency
                except Exception:
                    pass
                return current_app.config.get(
                    "DEFAULT_CURRENCY", CurrencyService.DEFAULT_BASE
                )
        except Exception:
            pass
        return CurrencyService.DEFAULT_BASE

    FALLBACK_RATES = {
        "ILS": Decimal("1.00"),
        "USD": Decimal("0.27"),
        "EUR": Decimal("0.25"),
        "GBP": Decimal("0.21"),
        "JOD": Decimal("0.19"),
        "AED": Decimal("0.99"),
        "SAR": Decimal("1.02"),
        "KWD": Decimal("0.083"),
        "BHD": Decimal("0.10"),
        "OMR": Decimal("0.104"),
        "QAR": Decimal("0.99"),
    }

    @staticmethod
    def get_all_rates(base=None):
        base = base or CurrencyService.get_base_currency()
        base = (base or "AED").upper()

        cache_entry = CurrencyService._rates_cache.get(base)
        if (
            cache_entry
            and (time.time() - cache_entry["timestamp"])
            < CurrencyService.CACHE_TTL_SECONDS
        ):
            return cache_entry["rates"].copy()

        rates = {}

        free_endpoints = [
            f"https://open.er-api.com/v6/latest/{base}",
            f"https://api.exchangerate-api.com/v4/latest/{base}",
            f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{base.lower()}.json",
        ]
        if REQUESTS_AVAILABLE:
            for url in free_endpoints:
                try:
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        fetched = None
                        if "rates" in data:
                            fetched = data["rates"]
                        elif base.lower() in data:
                            fetched = data[base.lower()]
                        if fetched:
                            for curr, rate in fetched.items():
                                try:
                                    rates[curr.upper()] = Decimal(str(rate)).quantize(
                                        RATE_QUANTUM, rounding=ROUND_HALF_UP
                                    )
                                except Exception:
                                    continue
                            rates[base] = Decimal("1.00")
                            CurrencyService._rates_cache[base] = {
                                "timestamp": time.time(),
                                "rates": rates,
                            }
                            CurrencyService._rates_source[base] = "live"
                            return rates.copy()
                except Exception as e:
                    print(f"Free API {url} failed: {e}")
                    continue

        if FOREX_AVAILABLE:
            try:
                c = CurrencyRates()
                fetched_rates = c.get_rates(base)

                for curr, rate in fetched_rates.items():
                    rates[curr] = Decimal(str(rate)).quantize(
                        RATE_QUANTUM, rounding=ROUND_HALF_UP
                    )

                rates[base] = Decimal("1.00")

                CurrencyService._rates_cache[base] = {
                    "timestamp": time.time(),
                    "rates": rates,
                }
                CurrencyService._rates_source[base] = "live"
                return rates.copy()
            except Exception as e:
                print(f"Forex API failed: {e}")

        def get_ils_value(target):
            if target == "ILS":
                return Decimal("1")
            return CurrencyService.FALLBACK_RATES.get(target, Decimal("1"))

        target_currencies = [
            "ILS",
            "USD",
            "EUR",
            "GBP",
            "JOD",
            "SAR",
            "KWD",
            "BHD",
            "OMR",
            "QAR",
            "AED",
        ]

        for curr in target_currencies:
            if curr == base:
                rates[curr] = Decimal("1.00")
            else:
                val_target = get_ils_value(curr)
                val_base = get_ils_value(base)

                rates[curr] = (val_target / val_base).quantize(
                    RATE_QUANTUM, rounding=ROUND_HALF_UP
                )

        CurrencyService._rates_cache[base] = {"timestamp": time.time(), "rates": rates}
        CurrencyService._rates_source[base] = "fallback"
        return rates.copy()

    @staticmethod
    def get_rate_provenance(currency):
        """'live', 'fallback' or 'unknown' for the given base currency cache."""
        return CurrencyService._rates_source.get((currency or "").upper(), "unknown")

    @staticmethod
    def invalidate_rates(currency=None):
        """Drop cached quotes so the next read observes a manual override."""
        if currency:
            key = (currency or "").upper()
            CurrencyService._rates_cache.pop(key, None)
            CurrencyService._rates_source.pop(key, None)
        else:
            CurrencyService._rates_cache.clear()
            CurrencyService._rates_source.clear()

    @staticmethod
    def get_manual_rate(from_currency, to_currency):
        """Return the newest valid owner-supplied rate, or ``None``.

        Manual rates are durable ``ExchangeRate`` rows (``is_manual=True``),
        so they survive restarts and are never overwritten by the provider
        refresh job. Query failures are non-fatal: the caller falls back to
        its normal live/fallback path.
        """
        try:
            from datetime import datetime, timezone

            from models import ExchangeRate

            now = datetime.now(timezone.utc)

            def _aware(value):
                if value is not None and value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value

            row = (
                ExchangeRate.query.filter_by(
                    from_currency=(from_currency or "").upper(),
                    to_currency=(to_currency or "").upper(),
                    is_manual=True,
                )
                .order_by(ExchangeRate.valid_from.desc())
                .first()
            )
            if row is not None:
                starts = _aware(row.valid_from)
                ends = _aware(row.valid_until)
                valid = starts is not None and starts <= now
                if valid and ends is not None:
                    valid = now <= ends
                if valid:
                    value = Decimal(str(row.rate))
                    if value.is_finite() and value > 0:
                        return value.quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)
        except Exception:
            pass
        return None

    @staticmethod
    def update_all_rates():
        """Refresh live rates, persist them and invalidate stale caches.

        Called by the scheduled ``celery_tasks.update_exchange_rates`` job.
        Only live-provider quotes are stored as non-manual ``ExchangeRate``
        rows; manual overrides are never touched. Returns a small summary so
        the task can report how many pairs were refreshed.
        """
        from datetime import datetime, timezone

        from models import Currency, ExchangeRate

        base = (CurrencyService.get_base_currency() or CurrencyService.DEFAULT_BASE).upper()

        # Drop any stale (possibly fallback) quote before asking the provider.
        CurrencyService._rates_cache.pop(base, None)
        CurrencyService._rates_source.pop(base, None)

        try:
            rates = CurrencyService.get_all_rates(base=base)
        except Exception:
            return {"success": False, "updated": 0, "base": base, "source": "unavailable"}

        if CurrencyService.get_rate_provenance(base) != "live":
            return {"success": False, "updated": 0, "base": base, "source": "fallback"}

        now = datetime.now(timezone.utc)
        currency_ids = {
            (row.code or "").upper(): row.id for row in Currency.query.all()
        }
        updated = 0
        try:
            for code, value in (rates or {}).items():
                code = str(code).upper()
                if code == base:
                    continue
                rate = Decimal(str(value))
                row = (
                    ExchangeRate.query.filter_by(
                        from_currency=base, to_currency=code, is_manual=False
                    )
                    .order_by(ExchangeRate.valid_from.desc())
                    .first()
                )
                if row is None:
                    row = ExchangeRate(
                        from_currency=base,
                        to_currency=code,
                        currency_id=currency_ids.get(code),
                        source="live",
                        is_manual=False,
                    )
                    db.session.add(row)
                row.rate = rate.quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)
                row.source = "live"
                row.valid_from = now
                updated += 1
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        # Force the next reader to observe the refreshed provider quote.
        CurrencyService._rates_cache.pop(base, None)
        CurrencyService._rates_source.pop(base, None)
        return {"success": True, "updated": updated, "base": base, "source": "live"}

    @staticmethod
    def get_exchange_rate(from_currency, to_currency=None, user_rate=None):
        """
        Get exchange rate between two currencies.
        Prioritises user-supplied rate, then checks CACHE, then live Forex,
        and finally uses static fallback rates.
        """
        if not from_currency:
            from_currency = CurrencyService.get_base_currency()
        if not to_currency:
            to_currency = CurrencyService.get_base_currency()

        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        if user_rate is not None:
            rate = Decimal(str(user_rate))
            if rate <= Decimal("0"):
                raise ValueError("Invalid user supplied exchange rate")
            trusted = False
            try:
                from flask import has_request_context
                if has_request_context():
                    from flask_login import current_user
                    trusted = bool(getattr(current_user, "is_authenticated", False)) and (
                        bool(getattr(current_user, "is_owner", False))
                        or getattr(getattr(current_user, "role", None), "slug", None)
                        == "super_admin"
                    )
            except Exception:
                trusted = False
            if trusted and rate <= Decimal("1000"):
                return rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            # Untrusted client rates are ignored; fall through to the server rate.

        if from_currency == to_currency:
            return Decimal("1")

        # Owner overrides are authoritative and durable; check them before
        # any cached or live quote so a manual fix is never masked by an
        # earlier provider response.
        manual = CurrencyService.get_manual_rate(from_currency, to_currency)
        if manual is not None:
            return manual

        cache_entry = CurrencyService._rates_cache.get(from_currency)
        if (
            cache_entry
            and (time.time() - cache_entry["timestamp"])
            < CurrencyService.CACHE_TTL_SECONDS
        ):
            cached_rate = cache_entry["rates"].get(to_currency)
            if cached_rate:
                return Decimal(str(cached_rate)).quantize(
                    RATE_QUANTUM, rounding=ROUND_HALF_UP
                )

        all_rates = CurrencyService.get_all_rates(base=from_currency)
        rate = all_rates.get(to_currency)
        if rate is None:
            # Never silently treat an unknown pair as 1:1 — callers must
            # supply an explicit manual rate instead of booking a fake FX
            # gain/loss against a currency we do not actually know.
            raise ValueError(
                f"No exchange rate available for {from_currency} to {to_currency}; "
                f"an explicit manual rate is required"
            )
        return Decimal(str(rate)).quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def format_amount(amount, currency=None, decimal_places=2):
        """تنسيق مبلغ بعملته بطريقة آمنة ثنائية الاتجاه (Bidi-safe).

        - يُعيد نصًا مثل '1,234.50 ILS' مع علامة U+200E (LRM) في البداية
          حتى لا ينقلب ترتيب المبلغ داخل الفقرات العربية (RTL).
        - أرقام لاتينية دائمًا (الأرقام العربية-الهندية مغلقة)، فواصل آلاف كل 3 خانات.
        - دالة نقية: لا تعتمد على سياق الطلب أو قاعدة البيانات.
        """
        if amount is None:
            raise ValueError("amount is required")
        if currency is None or not str(currency).strip():
            raise ValueError("currency is required")
        try:
            value = Decimal(str(amount))
        except Exception as exc:
            raise ValueError(f"Invalid amount: {amount!r}") from exc
        places = int(decimal_places) if decimal_places is not None else 2
        if places < 0:
            raise ValueError("decimal_places must be >= 0")
        quantum = Decimal(1).scaleb(-places)
        value = value.quantize(quantum, rounding=ROUND_HALF_UP)
        if value == 0:
            value = value.copy_abs()  # تجنّب '-0.00'
        body = f"{value:,}"
        return f"{LRM_MARK}{body} {str(currency).strip().upper()}"
