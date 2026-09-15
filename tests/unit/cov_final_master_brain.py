"""Backend test coverage for ai_knowledge/master_brain.py (real API)."""
from ai_knowledge.master_brain import MasterBrain, get_master_brain


class TestMasterBrain:
    """Test master brain functionality."""

    def test_singleton(self):
        assert get_master_brain() is get_master_brain()
        assert isinstance(get_master_brain(), MasterBrain)

    def test_attributes(self):
        brain = MasterBrain()
        assert isinstance(brain.name, str)
        assert isinstance(brain.version, str)

    def test_ask_returns_dict(self):
        brain = MasterBrain()
        result = brain.ask('What is the status of sales?')
        assert isinstance(result, dict)

    def test_explain_returns_str(self):
        brain = MasterBrain()
        result = brain.explain('sales decline')
        assert isinstance(result, str)
        assert len(result) > 0

    def test_quick_calc_vat(self):
        brain = MasterBrain()
        result = brain.quick_calc('vat', amount=100)
        assert result['success'] is True
        assert result['result'] == 5.0

    def test_quick_calc_unknown_formula(self):
        brain = MasterBrain()
        result = brain.quick_calc('no_such_formula', amount=100)
        assert result['success'] is False
        assert 'error' in result

    def test_validate_accounting_entry_balanced(self):
        brain = MasterBrain()
        result = brain.validate_accounting_entry(100.0, 100.0)
        assert result['is_balanced'] is True
        assert result['confidence'] == 1.0

    def test_validate_accounting_entry_unbalanced(self):
        brain = MasterBrain()
        result = brain.validate_accounting_entry(100.0, 90.0)
        assert result['is_balanced'] is False
        assert result['difference'] == 10.0
