from datetime import date


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


def test_budget_activate_success_commits(db):
    from extensions import db as _db
    from models.budget import Budget
    b = Budget(budget_number='B-2026-10', name_ar='تشغيل', fiscal_year=2026,
               period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
               status='draft', period_type='annual', total_budgeted=1000)
    _db.session.add(b)
    _db.session.commit()
    b.activate()
    assert b.status == 'active'
    assert Budget.query.filter_by(budget_number='B-2026-10').first().status == 'active'


def test_budget_close_draft_raises():
    from models.budget import Budget
    b = Budget(budget_number='B-2026-11', name_ar='إغلاق', fiscal_year=2026,
               period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
               status='draft')
    try:
        b.close()
        raise AssertionError('close on draft must raise')
    except ValueError:
        pass


def test_budget_line_variance_status_ar_branches():
    from models.budget import BudgetLine
    good = BudgetLine(budgeted_amount=100, actual_amount=103, variance=3, variance_percentage=3)
    warn = BudgetLine(budgeted_amount=100, actual_amount=110, variance=10, variance_percentage=10)
    bad = BudgetLine(budgeted_amount=100, actual_amount=80, variance=-20, variance_percentage=-20)
    assert (good.variance_status, good.variance_status_ar) == ('good', 'ممتاز')
    assert (warn.variance_status, warn.variance_status_ar) == ('warning', 'يحتاج متابعة')
    assert (bad.variance_status, bad.variance_status_ar) == ('danger', 'انحراف كبير')


def test_budget_full_lifecycle_activate_then_close(db):
    from extensions import db as _db
    from models.budget import Budget
    b = Budget(budget_number='B-2026-20', name_ar='دورة', fiscal_year=2026,
               period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
               status='draft', period_type='annual', total_budgeted=500)
    _db.session.add(b)
    _db.session.commit()
    b.activate()
    assert b.status == 'active'
    b.close()
    assert b.status == 'closed'