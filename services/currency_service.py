from decimal import Decimal

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
