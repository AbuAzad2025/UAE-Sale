from decimal import Decimal, ROUND_HALF_UP

try:
    from forex_python.converter import CurrencyRates
    FOREX_AVAILABLE = True
except ImportError:
    FOREX_AVAILABLE = False

class CurrencyService:
    
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
        if not FOREX_AVAILABLE:
            return CurrencyService.FALLBACK_RATES
        
        try:
            c = CurrencyRates()
            currencies = ['USD', 'EUR', 'GBP', 'SAR', 'KWD', 'BHD', 'OMR', 'QAR', 'AED']
            rates = {}
            
            for currency in currencies:
                if currency == base:
                    rates[currency] = Decimal('1.00')
                else:
                    try:
                        rate = c.get_rate(base, currency)
                        rates[currency] = Decimal(str(rate))
                    except:
                        rates[currency] = CurrencyService.FALLBACK_RATES.get(currency, Decimal('1.00'))
            
            return rates
        except:
            return CurrencyService.FALLBACK_RATES
    
    @staticmethod
    def convert(amount, from_currency, to_currency):
        if from_currency == to_currency:
            return Decimal(str(amount))
        
        if not FOREX_AVAILABLE:
            return Decimal(str(amount))
        
        try:
            c = CurrencyRates()
            rate = c.get_rate(from_currency, to_currency)
            return Decimal(str(amount)) * Decimal(str(rate))
        except:
            return Decimal(str(amount))

    @staticmethod
    def get_exchange_rate(from_currency, to_currency='AED', user_rate=None):
        """
        Get exchange rate between two currencies.
        Prioritises user-supplied rate, falls back to live Forex (if available),
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

        if FOREX_AVAILABLE:
            try:
                c = CurrencyRates()
                live_rate = c.get_rate(from_currency, to_currency)
                return Decimal(str(live_rate)).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
            except Exception:
                pass

        fallback = CurrencyService.FALLBACK_RATES

        def _aed_per(currency):
            if currency == 'AED':
                return Decimal('1')
            value = fallback.get(currency)
            if not value or value == 0:
                return None
            return (Decimal('1') / value)

        aed_per_from = _aed_per(from_currency)
        aed_per_to = _aed_per(to_currency)

        if aed_per_from is None or aed_per_to is None:
            return Decimal('1')

        rate = aed_per_from / aed_per_to
        return rate.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
