"""Wave-1 coverage tests for ai_knowledge/neural_engine.py.

Heavy-model paths are exercised via their rule-based fallbacks (isolated
models_dir) and via real insufficient-data DB paths. No training on large
data, no network.
"""
import os

import pytest

from ai_knowledge.neural_engine import AzadNeuralEngine, get_neural_engine

EXPECTED_MODELS = {
    'price_optimizer', 'sales_forecaster', 'customer_classifier',
    'fraud_detector', 'inventory_optimizer', 'demand_predictor',
    'profit_optimizer', 'churn_predictor', 'maintenance_predictor',
    'financial_planner',
}


@pytest.fixture
def engine(tmp_path):
    eng = AzadNeuralEngine()
    eng.models_dir = str(tmp_path)  # isolate: no repo .pkl files, no writes to repo
    return eng


def test_init_registers_ten_models_and_scalers(engine):
    assert set(engine.models) == EXPECTED_MODELS
    for name in EXPECTED_MODELS:
        assert name in engine.scalers
        assert name in engine.encoders
    assert engine.training_status == {}
    assert engine.performance_metrics == {}


def test_ensure_models_dir_creates_missing(engine, tmp_path):
    target = os.path.join(str(tmp_path), 'brand_new_subdir')
    engine.models_dir = target
    engine.ensure_models_dir()
    assert os.path.isdir(target)


def test_understand_intent_each_pattern(engine):
    cases = [
        ('حلل مبيعات sales performance', 'sales_analysis'),
        ('ما هو رصيد balance الديون receivable؟', 'customer_balance'),
        ('افحص مخزون inventory stock', 'inventory_check'),
        ('اقترح سعر price تسعير pricing', 'pricing'),
        ('توقع predict forecast المتوقع', 'forecast'),
    ]
    for msg, expected in cases:
        out = engine.understand_intent(msg)
        assert out['intent'] == expected, msg
        assert out['confidence'] > 0
        assert out['features']['word_count'] > 0


def test_understand_intent_unknown_message(engine):
    out = engine.understand_intent('xyzzy blorpt qqq')
    assert out['intent'] is None
    assert out['confidence'] == 0


def test_extract_text_features_languages(engine):
    ar = engine._extract_text_features('ما سعر المنتج 100؟')
    assert ar['language'] == 'ar'
    assert ar['has_numbers'] is True
    assert ar['has_question'] is True
    assert ar['length'] == len('ما سعر المنتج 100؟')
    en = engine._extract_text_features('hello world')
    assert en['language'] == 'en'
    assert en['has_numbers'] is False
    assert en['has_question'] is False


def test_validate_accounting_fallback_balanced(engine):
    out = engine.validate_accounting_entry(1000, 1000, 2, 'Sale')
    assert out['is_correct'] is True
    assert out['confidence'] == 1.0
    assert 'متوازن' in out['recommendation']


def test_validate_accounting_fallback_unbalanced(engine):
    out = engine.validate_accounting_entry(1000, 900, 2, 'Purchase')
    assert out['is_correct'] is False
    assert 'غير متوازن' in out['recommendation']


def test_validate_accounting_exception_returns_default(engine):
    out = engine.validate_accounting_entry('not-a-number', 100, 2, 'Sale')
    assert out['is_correct'] is True
    assert out['confidence'] == 0.5
    assert 'تعذر التحقق' in out['recommendation']


def test_detect_fraud_normal_transaction(engine):
    from datetime import datetime
    out = engine.detect_fraud({
        'amount_base': 5000, 'discount_amount': 100, 'subtotal': 5000,
        'paid_amount_base': 5000, 'sale_date': datetime(2026, 1, 5, 14, 0),
    })
    assert out['is_fraud'] is False
    # Fallback hardcodes risk_score=0.5 which maps to 'medium', even clean.
    assert out['risk_score'] == 0.5
    assert out['risk_level'] == 'medium'
    assert out['reasons'] == []
    assert 'طبيعية' in out['recommendation']


def test_detect_fraud_suspicious_transaction(engine):
    from datetime import datetime
    out = engine.detect_fraud({
        'amount_base': 150000, 'discount_amount': 90000, 'subtotal': 150000,
        'paid_amount_base': 0, 'sale_date': datetime(2026, 1, 5, 3, 0),
    })
    assert out['is_fraud'] is True
    assert out['risk_level'] in ('medium', 'high')
    joined = ' '.join(out['reasons'])
    assert 'مبلغ كبير' in joined
    assert 'خصم كبير' in joined
    assert 'غير معتاد' in joined
    assert 'آجل' in joined


def test_predict_optimal_price_fallback_margins(engine):
    regular = engine.predict_optimal_price(100, 2, 'regular')
    assert regular['predicted_price'] == pytest.approx(130.0)
    assert regular['margin_percent'] == pytest.approx(30.0)
    assert regular['model'] == 'rule_based'
    merchant = engine.predict_optimal_price(100, 2, 'merchant')
    assert merchant['predicted_price'] == pytest.approx(120.0)
    assert merchant['margin_percent'] == pytest.approx(20.0)
    partner = engine.predict_optimal_price(100, 2, 'partner')
    assert partner['predicted_price'] == pytest.approx(115.0)
    assert partner['margin_percent'] == pytest.approx(15.0)
    unknown = engine.predict_optimal_price(200, 1, 'vip')
    assert unknown['predicted_price'] == pytest.approx(250.0)


def test_predict_optimal_price_exception_fallback(engine, monkeypatch):
    monkeypatch.setattr(engine, '_load_model', lambda name: (_ for _ in ()).throw(RuntimeError('boom')))
    out = engine.predict_optimal_price(100, 1, 'regular')
    assert out['model'] == 'fallback'
    assert out['predicted_price'] == 125.0
    assert out['margin_percent'] == 25
    assert out['confidence'] == 0.5


def test_get_status_empty_and_with_dummy_file(engine, tmp_path):
    status = engine.get_status()
    assert status['total_models'] == 10
    assert status['trained_models'] == 0
    assert status['training_percentage'] == 0
    assert status['models']['price_optimizer'] == {'trained': False}
    dummy = tmp_path / 'price_optimizer.pkl'
    dummy.write_bytes(b'fake')
    status2 = engine.get_status()
    assert status2['trained_models'] == 1
    assert status2['models']['price_optimizer']['trained'] is True


def test_save_load_roundtrip_and_missing(engine):
    assert engine._load_model('price_optimizer') is False
    assert engine._is_model_loaded('price_optimizer') is False
    assert engine._save_model('price_optimizer') is True
    assert engine._load_model('price_optimizer') is True
    assert engine.load_all_models() == ['price_optimizer']


def test_train_functions_report_insufficient_data(db, engine):
    # BUG: the maintenance query's .outerjoin(SaleLine).outerjoin(Sale) is
    # ambiguous with the current models, so training always fails here.
    r = engine.train_maintenance_prediction()
    assert r['success'] is False
    assert 'FROM clause' in r['error']
    r = engine.train_accounting_assistant()
    assert r == {'success': False, 'error': 'Not enough accounting data'}
    r = engine.train_fraud_detector()
    assert r == {'success': False, 'error': 'Not enough sales for fraud detection'}
    r = engine.train_inventory_optimizer()
    assert r == {'success': False, 'error': 'Not enough inventory data'}


def test_train_functions_report_insufficient_data_part2(db, engine):
    r = engine.train_churn_predictor()
    assert r == {'success': False, 'error': 'Not enough customer data for churn'}
    r = engine.train_sales_forecaster()
    assert r == {'success': False, 'error': 'Not enough daily sales data'}
    r = engine.train_demand_predictor()
    assert r == {'success': False, 'error': 'Not enough demand data'}
    r = engine.train_profit_optimizer()
    assert r == {'success': False, 'error': 'Not enough profit data'}
    # BUG: the pricing query's .join() chain is ambiguous with the current
    # models, so training always fails here instead of reaching the
    # insufficient-data check.
    r = engine.train_price_optimizer()
    assert r['success'] is False
    assert 'FROM clause' in r['error']


def test_predict_cash_flow_untrained(engine):
    out = engine.predict_cash_flow(months_ahead=2)
    assert out == {'predictions': [], 'trend': 'unknown', 'error': 'Model not trained'}


def test_forecast_sales_untrained(engine):
    out = engine.forecast_sales(days_ahead=3)
    assert out == {'forecast': [], 'total_expected': 0, 'error': 'Model not trained'}


def test_predict_demand_untrained(engine):
    out = engine.predict_product_demand(1, days_ahead=3)
    assert out == {'forecast': [], 'total_expected': 0, 'error': 'Model not trained'}


def test_predict_maintenance_untrained(engine):
    out = engine.predict_maintenance_needs(1)
    assert out == {'needs_maintenance': False, 'confidence': 0, 'error': 'Model not trained'}


def test_classify_unknown_customer(db, engine):
    out = engine.classify_customer_intelligence(999999)
    assert out == {'classification': 'new', 'confidence': 1.0}


def test_classify_customer_fallback_rule(db, engine, test_customer):
    out = engine.classify_customer_intelligence(test_customer.id)
    assert out['classification'] == 'regular'
    assert out['confidence'] == 0.75
    assert out['characteristics']['sales_count'] == 0
    assert out['characteristics']['days_since_purchase'] == 365
    # No purchases for 365 days -> churn-risk recommendation branch.
    assert any('خطر' in rec for rec in out['recommendations'])


def test_optimize_stock_missing_product(db, engine):
    out = engine.optimize_stock_level(999999)
    assert out == {'optimal_stock': 0, 'reorder_point': 0}


def test_optimize_stock_fallback_crashes_on_decimal(db, engine, test_product):
    # BUG: _optimize_stock_internal mixes Decimal (Numeric columns) with
    # float in `current_stock / max(0.1, sales_rate)` -> TypeError, caught by
    # the wrapper which returns the zeros default.
    out = engine.optimize_stock_level(test_product.id)
    assert out == {'optimal_stock': 0, 'reorder_point': 0}


def test_neural_singleton():
    assert get_neural_engine() is get_neural_engine()
