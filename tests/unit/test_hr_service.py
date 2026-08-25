"""Unit tests for HRService — الرواتب والإجازات ودورة حياة الموظف."""
from datetime import date
from decimal import Decimal

import pytest

from models.hr import LeaveType
from services.hr_service import HRService


# 2026-11-02 = Monday .. 2026-11-08 = Sunday (Fri/Sat weekend)
WEEK_START = date(2026, 11, 2)
WEEK_END = date(2026, 11, 8)


@pytest.fixture
def department(db):
    return HRService.create_department('Sales Dept', 'قسم المبيعات', 'SAL', budget=100000)


@pytest.fixture
def employee(db, owner_user, department):
    return HRService.create_employee(
        user_id=owner_user.id,
        employee_number='EMP-001',
        department_id=department.id,
        position='Accountant',
        hire_date=date(2025, 1, 15),
        base_salary=Decimal('3000'),
        housing_allowance=500,
        transport_allowance=300,
    )


@pytest.fixture
def leave_types(db):
    HRService.ensure_default_leave_types()
    return {lt.code: lt for lt in LeaveType.query.all()}


class TestDepartments:
    def test_create_department(self, db, department):
        assert department.id is not None
        assert department.level == 0
        assert department.budget_amount == Decimal('100000')

    def test_duplicate_code_raises(self, db, department):
        with pytest.raises(ValueError, match='موجود مسبقاً'):
            HRService.create_department('Other', 'آخر', 'SAL')

    def test_child_inherits_parent_level(self, db, department):
        child = HRService.create_department('Sub', 'فرعي', 'SUB', parent_id=department.id)
        assert child.level == department.level + 1

    def test_missing_parent_raises(self, db):
        with pytest.raises(ValueError, match='الأب'):
            HRService.create_department('Orphan', 'يتيم', 'ORP', parent_id=99999)


class TestEmployees:
    def test_create_sets_leave_balances(self, db, employee):
        assert employee.annual_leave_balance == 30
        assert employee.sick_leave_balance == 15
        assert employee.personal_leave_balance == 5
        assert employee.base_salary == Decimal('3000')

    def test_duplicate_user_raises(self, db, owner_user, employee):
        with pytest.raises(ValueError, match='ملف موظف بالفعل'):
            HRService.create_employee(
                user_id=owner_user.id, employee_number='EMP-X',
                department_id=None, position='X',
                hire_date=date(2026, 1, 1), base_salary=1000)

    def test_duplicate_number_raises(self, db, seller_user, employee):
        with pytest.raises(ValueError, match='EMP-001'):
            HRService.create_employee(
                user_id=seller_user.id, employee_number='EMP-001',
                department_id=None, position='X',
                hire_date=date(2026, 1, 1), base_salary=1000)

    def test_missing_department_raises(self, db, seller_user):
        with pytest.raises(ValueError, match='القسم غير موجود'):
            HRService.create_employee(
                user_id=seller_user.id, employee_number='EMP-Y',
                department_id=99999, position='X',
                hire_date=date(2026, 1, 1), base_salary=1000)

    def test_update_allowed_fields_only(self, db, employee):
        HRService.update_employee(employee, base_salary='3500', not_a_field='ignored')
        assert employee.base_salary == Decimal('3500')
        assert not hasattr(employee, 'not_a_field') or getattr(employee, 'not_a_field', None) != 'ignored'

    def test_inactive_employee_rejected_for_payslip(self, db, employee):
        HRService.update_employee(employee, employment_status='terminated')
        with pytest.raises(ValueError, match='غير نشط'):
            HRService.generate_payslip(
                employee.id, date(2026, 11, 1), date(2026, 11, 30), date(2026, 12, 1))


class TestWorkingDays:
    def test_excludes_fri_sat(self, db):
        days = HRService._count_working_days(WEEK_START, WEEK_END)
        assert days == 5

    def test_period_days(self, db):
        # Nov 2026: 30 days, Fridays 6/13/20/27 + Saturdays 7/14/21/28 = 8 off
        assert HRService._working_days_in_period(date(2026, 11, 1), date(2026, 11, 30)) == 22


class TestLeaveFlow:
    def test_request_counts_working_days(self, db, employee, leave_types):
        leave = HRService.request_leave(
            employee.id, leave_types['annual'].id, WEEK_START, WEEK_END, reason='سنوية')
        assert leave.days == 5
        assert leave.status == 'pending'

    def test_insufficient_balance_raises(self, db, employee, leave_types):
        # maternity has no tracked balance -> treated as 0
        with pytest.raises(ValueError, match='غير كافٍ'):
            HRService.request_leave(
                employee.id, leave_types['maternity'].id, WEEK_START, WEEK_END)

    def test_inactive_employee_cannot_request(self, db, employee, leave_types):
        HRService.update_employee(employee, employment_status='resigned')
        with pytest.raises(ValueError, match='غير نشط'):
            HRService.request_leave(
                employee.id, leave_types['annual'].id, WEEK_START, WEEK_END)

    def test_overlapping_requests_blocked(self, db, employee, leave_types):
        HRService.request_leave(
            employee.id, leave_types['annual'].id, WEEK_START, WEEK_END)
        with pytest.raises(ValueError, match='يتقاطع'):
            HRService.request_leave(
                employee.id, leave_types['sick'].id,
                date(2026, 11, 4), date(2026, 11, 10))

    def test_approve_deducts_balance_and_cancel_restores(self, db, owner_user, employee, leave_types):
        before = employee.annual_leave_balance
        leave = HRService.request_leave(
            employee.id, leave_types['annual'].id, WEEK_START, WEEK_END)

        HRService.approve_leave(leave.id, owner_user.id)
        db.session.refresh(employee)
        assert employee.annual_leave_balance == before - 5

        with pytest.raises(ValueError, match='المراجعة'):
            HRService.approve_leave(leave.id, owner_user.id)

        HRService.cancel_leave(leave.id)
        db.session.refresh(employee)
        assert employee.annual_leave_balance == before

    def test_reject_keeps_balance(self, db, owner_user, employee, leave_types):
        before = employee.sick_leave_balance
        leave = HRService.request_leave(
            employee.id, leave_types['sick'].id, WEEK_START, WEEK_END)
        HRService.reject_leave(leave.id, owner_user.id, reason='لا شهادة')
        db.session.refresh(employee)
        assert employee.sick_leave_balance == before
        assert leave.status == 'rejected'
        assert leave.rejection_reason == 'لا شهادة'


class TestPayroll:
    def test_generate_payslip_math(self, db, employee):
        payslip = HRService.generate_payslip(
            employee.id, date(2026, 11, 1), date(2026, 11, 30), date(2026, 12, 1),
            overtime_hours=2, overtime_rate=1.5, leave_days_unpaid=1,
        )
        # per_day = 3000/22 = 136.36 ; hourly = 3000/240 = 12.50 ; OT = 37.50
        assert payslip.overtime_amount == Decimal('37.50')
        assert payslip.leave_deduction == Decimal('136.36')
        expected_net = Decimal('3000') + Decimal('500') + Decimal('300') \
            + Decimal('37.50') - Decimal('136.36')
        assert payslip.net_salary == expected_net
        assert payslip.payslip_number.startswith('PAYSLIP')

    def test_duplicate_period_raises(self, db, employee):
        HRService.generate_payslip(
            employee.id, date(2026, 11, 1), date(2026, 11, 30), date(2026, 12, 1))
        with pytest.raises(ValueError, match='بالفعل لهذه الفترة'):
            HRService.generate_payslip(
                employee.id, date(2026, 11, 1), date(2026, 11, 30), date(2026, 12, 1))

    def test_bulk_payroll_mixed_results(self, db, owner_user, employee, seller_user):
        second = HRService.create_employee(
            user_id=seller_user.id, employee_number='EMP-002',
            department_id=None, position='Clerk',
            hire_date=date(2026, 1, 1), base_salary=2000)
        HRService.update_employee(second, employment_status='terminated')

        result = HRService.generate_bulk_payroll(
            date(2026, 11, 1), date(2026, 11, 30), date(2026, 12, 1),
            created_by=owner_user.id,
            adjustments_map={employee.id: {'bonus': 100}},
        )
        assert result['success_count'] == 1
        assert result['payslips'][0].bonus == Decimal('100')

    def test_payslip_approval_chain(self, db, owner_user, employee):
        payslip = HRService.generate_payslip(
            employee.id, date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 1))

        with pytest.raises(ValueError, match='تسجيل الدفع'):
            payslip.mark_paid()

        payslip.approve(owner_user.id)
        assert payslip.status == 'approved'
        payslip.mark_paid()
        assert payslip.status == 'paid'


class TestDefaultsAndStats:
    def test_default_leave_types_idempotent(self, db, leave_types):
        HRService.ensure_default_leave_types()
        assert LeaveType.query.count() == 6

    def test_hr_stats(self, db, employee, leave_types):
        stats = HRService.get_hr_stats()
        assert stats['total_employees'] == 1
        assert stats['active_departments'] == 1
        assert stats['total_monthly_payroll'] == float(Decimal('3800'))

        from datetime import timedelta
        employee.visa_expiry = date.today() + timedelta(days=30)
        db.session.commit()
        stats = HRService.get_hr_stats()
        assert stats['expiring_visas'] == 1
