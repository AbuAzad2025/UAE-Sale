from decimal import Decimal
from forex_python.converter import CurrencyRates

class CurrencyService:
    
    @staticmethod
    def get_all_rates(base='AED'):
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
                        rates[currency] = Decimal('1.00')
            
            return rates
        except:
            return {
                'AED': Decimal('1.00'),
                'USD': Decimal('0.27'),
                'EUR': Decimal('0.25'),
                'GBP': Decimal('0.22'),
                'SAR': Decimal('1.02')
            }
    
    @staticmethod
    def convert(amount, from_currency, to_currency):
        if from_currency == to_currency:
            return Decimal(str(amount))
        
        try:
            c = CurrencyRates()
            rate = c.get_rate(from_currency, to_currency)
            return Decimal(str(amount)) * Decimal(str(rate))
        except:
            return Decimal(str(amount))
