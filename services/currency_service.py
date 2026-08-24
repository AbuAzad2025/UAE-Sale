from decimal import Decimal, ROUND_HALF_UP
import time

try:
    from forex_python.converter import CurrencyRates
    FOREX_AVAILABLE = True
except ImportError:
    FOREX_AVAILABLE = False


class CurrencyService:

    CACHE_TTL_SECONDS = 300  # 5 دقائق
    _rates_cache = {}

    FALLBACK_RATES = {
        'AED': Decimal('1.00'),
        'USD': Decimal('0.27'),
        'EUR': Decimal('0.25'),
        'GBP': Decimal('0.22'),
        'SAR': Decimal('1.02'),
        'KWD': Decimal('0.08'),
        'BHD': Decimal('0.10'),
        'OMR': Decimal('0.10'),
        'QAR': Decimal('0.99')
    }

    @staticmethod
    def get_all_rates(base='AED'):
        base = (base or 'AED').upper()

        # Check cache first
        cache_entry = CurrencyService._rates_cache.get(base)
        if cache_entry and (time.time() - cache_entry['timestamp']) < CurrencyService.CACHE_TTL_SECONDS:
            return cache_entry['rates'].copy()

        rates = {}

        # Try fetching live rates
        if FOREX_AVAILABLE:
            try:
                c = CurrencyRates()
                # get_rates returns a dict of rates for the base currency
                # This is a SINGLE API call, much faster than a loop
                fetched_rates = c.get_rates(base)

                # Convert to Decimal
                for curr, rate in fetched_rates.items():
                    rates[curr] = Decimal(str(rate))

                # Ensure base currency is 1.0
                rates[base] = Decimal('1.00')

                # Cache the result
                CurrencyService._rates_cache[base] = {'timestamp': time.time(), 'rates': rates}
                return rates.copy()
            except Exception as e:
                # Log error if possible, or just continue to fallback
                print(f"Forex API failed: {e}")

        # Fallback if API fails or not available
        # Recalculate fallback rates based on the requested base
        # Our static FALLBACK_RATES are "Value of 1 AED in X Currency"

        # Helper to get value of 1 AED in Target Currency
        def get_aed_value(target):
            if target == 'AED':
                return Decimal('1')
            return CurrencyService.FALLBACK_RATES.get(target, Decimal('1'))

        _ = get_aed_value(base)  # How many Target units for 1 AED

        # We want: How many Target units for 1 Base unit?
        # Rate = (1 AED in Target) / (1 AED in Base)
        # Wait, if FALLBACK is "1 AED = X Target"
        # Then "1 Base = (1 AED in Base) units"
        # 1 Base = (1/Base_AED_Val) AED
        # Value in Target = (1/Base_AED_Val) * (Target_AED_Val)

        target_currencies = ['USD', 'EUR', 'GBP', 'SAR', 'KWD', 'BHD', 'OMR', 'QAR', 'AED']

        for curr in target_currencies:
            if curr == base:
                rates[curr] = Decimal('1.00')
            else:
                # Calculate Cross Rate from Fallback
                val_target = get_aed_value(curr)
                val_base = get_aed_value(base)

                # Cross rate: Base -> Target
                # 1 Base = (val_target / val_base) Target
                rates[curr] = (val_target / val_base).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)

        CurrencyService._rates_cache[base] = {'timestamp': time.time(), 'rates': rates}
        return rates

    @staticmethod
    def get_exchange_rate(from_currency, to_currency='AED', user_rate=None):
        """
        Get exchange rate between two currencies.
        Prioritises user-supplied rate, then checks CACHE, then live Forex,
        and finally uses static fallback rates.
        """
        if not from_currency:
            from_currency = 'AED'
        if not to_currency:
            to_currency = 'AED'

        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        if user_rate is not None:
            rate = Decimal(str(user_rate))
            if rate <= Decimal('0'):
                raise ValueError('Invalid user supplied exchange rate')
            return rate.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)

        if from_currency == to_currency:
            return Decimal('1')

        # CHECK CACHE FIRST (Performance Fix)
        # We check the cache for the 'from_currency' as base
        cache_entry = CurrencyService._rates_cache.get(from_currency)
        if cache_entry and (time.time() - cache_entry['timestamp']) < CurrencyService.CACHE_TTL_SECONDS:
            cached_rate = cache_entry['rates'].get(to_currency)
            if cached_rate:
                return cached_rate

        # If not in cache, try to fetch/refresh cache for 'from_currency'
        # This calls the optimized get_all_rates which handles API/Fallback + Caching
        all_rates = CurrencyService.get_all_rates(base=from_currency)
        return all_rates.get(to_currency, Decimal('1'))
