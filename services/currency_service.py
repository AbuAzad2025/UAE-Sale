import requests
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from flask import current_app
from extensions import db, cache
from models import Currency, ExchangeRate


class CurrencyService:
    
    @staticmethod
    def get_exchange_rate(from_currency, to_currency='AED', user_rate=None):
        if from_currency == to_currency:
            return Decimal('1.0')
        
        if user_rate is not None:
            return Decimal(str(user_rate))
        
        rate = CurrencyService._get_cached_rate(from_currency, to_currency)
        
        if rate:
            return rate
        
        rate = CurrencyService._fetch_rate_from_api(from_currency, to_currency)
        
        if rate:
            CurrencyService._cache_rate(from_currency, to_currency, rate)
            return rate
        
        rate = CurrencyService._get_latest_db_rate(from_currency, to_currency)
        
        if rate:
            return rate
        
        raise ValueError(f'لم يتم العثور على سعر صرف {from_currency}/{to_currency}')
    
    @staticmethod
    def _get_cached_rate(from_currency, to_currency):
        cache_key = f'exchange_rate:{from_currency}:{to_currency}'
        cached = cache.get(cache_key)
        
        if cached:
            current_app.logger.debug(f'Cache hit for {from_currency}/{to_currency}')
            return Decimal(str(cached))
        
        return None
    
    @staticmethod
    def _cache_rate(from_currency, to_currency, rate):
        cache_key = f'exchange_rate:{from_currency}:{to_currency}'
        timeout = current_app.config.get('CURRENCY_CACHE_TIMEOUT', 3600)
        cache.set(cache_key, float(rate), timeout=timeout)
    
    @staticmethod
    def _fetch_rate_from_api(from_currency, to_currency):
        try:
            api_key = current_app.config.get('CURRENCY_API_KEY')
            api_url = current_app.config.get('CURRENCY_API_URL')
            fallback_urls = current_app.config.get('CURRENCY_API_FALLBACKS', [])
            timeout = current_app.config.get('CURRENCY_API_TIMEOUT', 5)
            
            if api_key and api_url:
                url = api_url.format(api_key=api_key, base=to_currency)
                response = requests.get(url, timeout=timeout)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if 'conversion_rates' in data:
                        rates = data['conversion_rates']
                    elif 'rates' in data:
                        rates = data['rates']
                    else:
                        rates = {}
                    
                    if from_currency in rates:
                        rate = Decimal(str(rates[from_currency]))
                        current_app.logger.info(f'API: {from_currency}/{to_currency} = {rate}')
                        
                        CurrencyService._save_rate_to_db(from_currency, to_currency, rate, source='API')
                        
                        return rate
            
            for fallback_url in fallback_urls:
                try:
                    # Handle different API formats
                    if '{base_lower}' in fallback_url:
                        url = fallback_url.format(base_lower=to_currency.lower())
                        response = requests.get(url, timeout=timeout)
                        
                        if response.status_code == 200:
                            data = response.json()
                            # This API format: {"aed": {"usd": 0.27, ...}}
                            base_lower = to_currency.lower()
                            if base_lower in data and from_currency.lower() in data[base_lower]:
                                rate_value = data[base_lower][from_currency.lower()]
                                rate = Decimal(str(rate_value))
                                current_app.logger.info(f'Fallback API (fawazahmed0): {from_currency}/{to_currency} = {rate}')
                                
                                CurrencyService._save_rate_to_db(from_currency, to_currency, rate, source='Fallback API (fawazahmed0)')
                                
                                return rate
                    elif 'base_currency' in fallback_url:
                        url = fallback_url.format(base=to_currency)
                        response = requests.get(url, timeout=timeout)
                        
                        if response.status_code == 200:
                            data = response.json()
                            # This API format: {"data": {"USD": 0.27, ...}}
                            if 'data' in data and from_currency in data['data']:
                                rate_value = data['data'][from_currency]
                                rate = Decimal(str(rate_value))
                                current_app.logger.info(f'Fallback API (freecurrencyapi): {from_currency}/{to_currency} = {rate}')
                                
                                CurrencyService._save_rate_to_db(from_currency, to_currency, rate, source='Fallback API (freecurrencyapi)')
                                
                                return rate
                    else:
                        # Request with from_currency as base to get correct rate
                        url = fallback_url.format(base=from_currency)
                        response = requests.get(url, timeout=timeout)
                        
                        if response.status_code == 200:
                            data = response.json()
                            rates = data.get('rates', {})
                            
                            if to_currency in rates:
                                rate = Decimal(str(rates[to_currency]))
                                current_app.logger.info(f'Fallback API: {from_currency}/{to_currency} = {rate}')
                                
                                CurrencyService._save_rate_to_db(from_currency, to_currency, rate, source='Fallback API')
                                
                                return rate
                
                except Exception as e:
                    current_app.logger.warning(f'Fallback API failed ({fallback_url[:50]}...): {e}')
                    continue
        
        except Exception as e:
            current_app.logger.error(f'API fetch failed: {e}')
        
        return None
    
    @staticmethod
    def _save_rate_to_db(from_currency, to_currency, rate, source='API'):
        try:
            currency = Currency.query.filter_by(code=from_currency).first()
            
            if not currency:
                currency = Currency(code=from_currency, name=from_currency)
                db.session.add(currency)
                db.session.flush()
            
            exchange_rate = ExchangeRate(
                from_currency=from_currency,
                to_currency=to_currency,
                currency_id=currency.id,
                rate=rate,
                source=source,
                is_manual=False,
            )
            
            db.session.add(exchange_rate)
            db.session.commit()
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Failed to save rate to DB: {e}')
    
    @staticmethod
    def _get_latest_db_rate(from_currency, to_currency):
        try:
            currency = Currency.query.filter_by(code=from_currency).first()
            
            if not currency:
                return None
            
            exchange_rate = ExchangeRate.query.filter_by(
                from_currency=from_currency,
                to_currency=to_currency
            ).order_by(
                ExchangeRate.created_at.desc()
            ).first()
            
            if exchange_rate:
                current_app.logger.info(f'DB rate: {from_currency}/{to_currency} = {exchange_rate.rate}')
                return exchange_rate.rate
        
        except Exception as e:
            current_app.logger.error(f'DB rate fetch failed: {e}')
        
        return None
    
    @staticmethod
    def set_manual_rate(from_currency, to_currency, rate, user_id=None):
        try:
            currency = Currency.query.filter_by(code=from_currency).first()
            
            if not currency:
                currency = Currency(code=from_currency, name=from_currency)
                db.session.add(currency)
                db.session.flush()
            
            exchange_rate = ExchangeRate(
                from_currency=from_currency,
                to_currency=to_currency,
                currency_id=currency.id,
                rate=Decimal(str(rate)),
                source='Manual',
                is_manual=True,
                created_by=user_id,
            )
            
            db.session.add(exchange_rate)
            db.session.commit()
            
            CurrencyService._cache_rate(from_currency, to_currency, Decimal(str(rate)))
            
            return True
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Failed to set manual rate: {e}')
            return False
    
    @staticmethod
    def get_all_rates(base_currency='AED'):
        rates = {}
        
        for currency_code in ['USD', 'EUR', 'GBP', 'SAR', 'KWD', 'QAR', 'OMR', 'BHD']:
            if currency_code == base_currency:
                rates[currency_code] = 1.0
                continue
            
            try:
                rate = CurrencyService.get_exchange_rate(currency_code, base_currency)
                rates[currency_code] = float(rate)
            except Exception:
                rates[currency_code] = None
        
        return rates
    
    @staticmethod
    def update_all_rates():
        updated = 0
        failed = 0
        
        for currency_code in ['USD', 'EUR', 'GBP', 'SAR', 'KWD', 'QAR', 'OMR', 'BHD']:
            try:
                rate = CurrencyService._fetch_rate_from_api(currency_code, 'AED')
                if rate:
                    updated += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        
        return {'updated': updated, 'failed': failed}

