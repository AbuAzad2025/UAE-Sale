from unittest.mock import patch


def test_should_retrain_first_time():
    from ai_knowledge.auto_retraining import AutoRetrainingScheduler
    with patch('models.Sale') as MockSale:
        MockSale.query.filter_by.return_value.count.side_effect = [120]
        with patch.object(AutoRetrainingScheduler, 'get_last_training_info', return_value=None):
            assert AutoRetrainingScheduler.should_retrain() is True


def test_check_and_train_no_retraining():
    from ai_knowledge.auto_retraining import AutoRetrainingScheduler
    with patch.object(AutoRetrainingScheduler, 'should_retrain', return_value=False):
        result = AutoRetrainingScheduler.check_and_train_if_needed()
        assert result == {'message': 'No retraining needed'}


def test_should_retrain_false_with_few_sales_no_history(db, tmp_path, monkeypatch):
    from ai_knowledge.auto_retraining import AutoRetrainingScheduler
    monkeypatch.setattr(
        AutoRetrainingScheduler, 'TRAINING_LOG_FILE', str(tmp_path / 'history.json'))
    assert AutoRetrainingScheduler.should_retrain() is False


def test_retrain_threshold_flow_with_real_sales(db, test_customer, owner_user, tmp_path, monkeypatch):
    from decimal import Decimal
    from models import Sale
    from extensions import db as _db
    from ai_knowledge.auto_retraining import AutoRetrainingScheduler
    monkeypatch.setattr(
        AutoRetrainingScheduler, 'TRAINING_LOG_FILE', str(tmp_path / 'history.json'))
    rows = [
        Sale(
            sale_number='S-RETRAIN-%04d' % i,
            customer_id=test_customer.id, seller_id=owner_user.id,
            total_amount=Decimal('100.000'), amount_base=Decimal('100.000'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('100.000'), currency='AED',
            exchange_rate=Decimal('1'), payment_status='unpaid',
            status='confirmed', is_active=True,
        )
        for i in range(105)
    ]
    _db.session.add_all(rows)
    _db.session.commit()
    assert AutoRetrainingScheduler.should_retrain() is True
    AutoRetrainingScheduler.log_training(105, {'success': True})
    info = AutoRetrainingScheduler.get_last_training_info()
    assert info['sales_count'] == 105
    assert info['results'] == {'success': True}


def test_trigger_retraining_writes_log(db, tmp_path, monkeypatch):
    import sys
    import types
    from ai_knowledge.auto_retraining import AutoRetrainingScheduler
    monkeypatch.setattr(
        AutoRetrainingScheduler, 'TRAINING_LOG_FILE', str(tmp_path / 'history.json'))
    fake_neural = types.SimpleNamespace(
        train_all_models=lambda: {'success': True, 'models': 3})
    fake_mod = types.ModuleType('fake_neural_engine')
    fake_mod.get_neural_engine = lambda: fake_neural
    monkeypatch.setitem(sys.modules, 'ai_knowledge.neural_engine', fake_mod)
    results = AutoRetrainingScheduler.trigger_retraining()
    assert results == {'success': True, 'models': 3}
    info = AutoRetrainingScheduler.get_last_training_info()
    assert info['sales_count'] == 0


def _bulk_sales(test_customer, owner_user, prefix, count):
    from decimal import Decimal
    from models import Sale
    from extensions import db as _db
    rows = [
        Sale(
            sale_number='%s-%04d' % (prefix, i),
            customer_id=test_customer.id, seller_id=owner_user.id,
            total_amount=Decimal('100.000'), amount_base=Decimal('100.000'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('100.000'), currency='AED',
            exchange_rate=Decimal('1'), payment_status='unpaid',
            status='confirmed', is_active=True,
        )
        for i in range(count)
    ]
    _db.session.add_all(rows)
    _db.session.commit()
    return rows


def test_should_retrain_via_weekly_threshold(db, test_customer, owner_user, tmp_path, monkeypatch):
    import json
    from datetime import datetime, timedelta
    from ai_knowledge.auto_retraining import AutoRetrainingScheduler
    log = tmp_path / 'history.json'
    monkeypatch.setattr(AutoRetrainingScheduler, 'TRAINING_LOG_FILE', str(log))
    log.write_text(json.dumps([{
        'timestamp': (datetime.now() - timedelta(days=10)).isoformat(),
        'sales_count': 0,
        'results': {},
    }]))
    _bulk_sales(test_customer, owner_user, 'S-WEEKLY', 60)
    assert AutoRetrainingScheduler.should_retrain() is True


def test_check_and_train_runs_real_retraining(db, test_customer, owner_user, tmp_path, monkeypatch):
    import sys
    import types
    from ai_knowledge.auto_retraining import AutoRetrainingScheduler
    monkeypatch.setattr(
        AutoRetrainingScheduler, 'TRAINING_LOG_FILE', str(tmp_path / 'history.json'))
    fake_neural = types.SimpleNamespace(
        train_all_models=lambda: {'success': True, 'models': 2})
    fake_mod = types.ModuleType('fake_neural_engine2')
    fake_mod.get_neural_engine = lambda: fake_neural
    monkeypatch.setitem(sys.modules, 'ai_knowledge.neural_engine', fake_mod)
    _bulk_sales(test_customer, owner_user, 'S-FULL', 105)
    result = AutoRetrainingScheduler.check_and_train_if_needed()
    assert result == {'success': True, 'models': 2}
    assert AutoRetrainingScheduler.get_last_training_info()['sales_count'] == 105