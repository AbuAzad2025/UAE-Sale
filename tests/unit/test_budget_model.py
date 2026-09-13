from flask import Flask

def test_budget_model_repr_and_status_ar():
    from models.budget import Budget
    b = Budget(budget_number='B-2026-01', name_ar='اختبار', fiscal_year=2026, period_start='2026-01-01', period_end='2026-12-31', status='draft', period_type='annual')
    assert 'B-2026-01' in repr(b)
    assert b.status_ar == 'مسودة'
    assert b.period_type_ar == 'سنوية'


def test_budget_activate_raises_for_non_draft():
    from models.budget import Budget
    b = Budget(budget_number='B-2026-02', name_ar='اختبار2', fiscal_year=2026, period_start='2026-01-01', period_end='2026-12-31', status='active')
    try:
        b.activate()
        assert False, 'Should have raised ValueError'
    except ValueError:
        pass
