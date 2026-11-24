"""HR income-tax and daily-wage correctness."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

from decimal import Decimal
from app import create_app
from models.hr import Employee


def test_withholding_tax_math():
    app = create_app()
    with app.app_context():
        e = Employee(income_tax_rate=Decimal("10"), tax_exemption=Decimal("3000"))
        assert e.withholding_tax(Decimal("9500")) == Decimal("650.00")
        assert e.withholding_tax(Decimal("3000")) == Decimal("0.00")
        assert e.withholding_tax(Decimal("0")) == Decimal("0.00")
        e2 = Employee(income_tax_rate=Decimal("5"), tax_exemption=Decimal("1500"))
        assert e2.withholding_tax(Decimal("5000")) == Decimal("175.00")


def test_daily_worker_detection():
    app = create_app()
    with app.app_context():
        assert Employee(is_daily_wage=True).is_daily_worker is True
        assert Employee(contract_type="daily").is_daily_worker is True
        assert Employee(contract_type="full_time").is_daily_worker is False


def test_migration_and_fields_in_source():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    model = open(os.path.join(root, 'models', 'hr.py'), encoding='utf-8').read()
    for f in ('income_tax_rate', 'tax_exemption', 'is_daily_wage', 'daily_wage_rate'):
        assert f in model
    svc = open(os.path.join(root, 'services', 'hr_service.py'), encoding='utf-8').read()
    assert 'withholding_tax(payslip.total_earnings)' in svc
    assert 'days_worked' in svc
    mig = open(os.path.join(root, 'migrations', 'versions',
                            'c08_hr_tax_daily_wage.py'), encoding='utf-8').read()
    assert 'income_tax_rate' in mig and 'daily_wage_rate' in mig


def test_localised_status_labels():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for fn in ('view_employee.html', 'employees.html'):
        src = open(os.path.join(root, 'templates', 'hr', fn),
                   encoding='utf-8').read()
        assert 'employment_status_label' in src
    payslip = open(os.path.join(root, 'templates', 'hr', 'view_payslip.html'),
                   encoding='utf-8').read()
    assert 'status_label' in payslip and 'status_ar' not in payslip
