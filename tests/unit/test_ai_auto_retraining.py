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
