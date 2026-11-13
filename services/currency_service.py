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
            from flask import current_app, has_request_context

            if has_request_context():
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
        return rates.copy()

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
            return rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

        if from_currency == to_currency:
            return Decimal("1")

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
        return all_rates.get(to_currency, Decimal("1"))

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
