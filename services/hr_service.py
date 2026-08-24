"""
HR Service - Salary Calculation, Leave Management, Payroll Processing
"""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from flask import current_app
from extensions import db
from models.hr import Employee, Department, LeaveType, LeaveRequest, Payslip, PayslipLine
from utils.helpers import generate_number


class HRService:
    """Core HR business logic"""

    # ---- Department ----

    @staticmethod
    def create_department(name, name_ar, code, parent_id=None, manager_id=None, budget=0):
        existing = Department.query.filter_by(code=code).first()
        if existing:
            raise ValueError(f'كود القسم "{code}" موجود مسبقاً')

        level = 0
        if parent_id:
            parent = db.session.get(Department, parent_id)
            if not parent:
                raise ValueError('القسم الأب غير موجود')
            level = parent.level + 1

        dept = Department(
            name=name,
            name_ar=name_ar,
            code=code,
            parent_id=parent_id,
            level=level,
            manager_id=manager_id,
            budget_amount=Decimal(str(budget)),
        )
        db.session.add(dept)
        db.session.commit()
        return dept

    # ---- Employee ----

    @staticmethod
    def create_employee(user_id, employee_number, department_id, position,
                        hire_date, base_salary, contract_type='full_time',
                        **kwargs):
        """Create an employee profile linked to a user"""
        # Validate uniqueness
        existing = Employee.query.filter_by(user_id=user_id).first()
        if existing:
            raise ValueError('هذا المستخدم لديه ملف موظف بالفعل')

        existing_num = Employee.query.filter_by(employee_number=employee_number).first()
        if existing_num:
            raise ValueError(f'رقم الموظف "{employee_number}" موجود مسبقاً')

        # Validate department
        if department_id:
            dept = db.session.get(Department, department_id)
            if not dept:
                raise ValueError('القسم غير موجود')

        emp = Employee(
            user_id=user_id,
            employee_number=employee_number,
            department_id=department_id,
            position=position,
            position_ar=kwargs.get('position_ar'),
            hire_date=hire_date,
            contract_type=contract_type,
            base_salary=Decimal(str(base_salary)),
            salary_currency=kwargs.get('salary_currency', 'AED'),
            payment_frequency=kwargs.get('payment_frequency', 'monthly'),
            bank_name=kwargs.get('bank_name'),
            bank_account_number=kwargs.get('bank_account_number'),
            iban=kwargs.get('iban'),
            housing_allowance=Decimal(str(kwargs.get('housing_allowance', 0))),
            transport_allowance=Decimal(str(kwargs.get('transport_allowance', 0))),
            phone_allowance=Decimal(str(kwargs.get('phone_allowance', 0))),
            other_allowances=Decimal(str(kwargs.get('other_allowances', 0))),
            national_id=kwargs.get('national_id'),
            passport_number=kwargs.get('passport_number'),
            visa_number=kwargs.get('visa_number'),
            visa_expiry=kwargs.get('visa_expiry'),
            date_of_birth=kwargs.get('date_of_birth'),
            gender=kwargs.get('gender'),
            nationality=kwargs.get('nationality'),
            marital_status=kwargs.get('marital_status'),
            emergency_contact_name=kwargs.get('emergency_contact_name'),
            emergency_contact_phone=kwargs.get('emergency_contact_phone'),
            annual_leave_days=kwargs.get('annual_leave_days', 30),
            sick_leave_days=kwargs.get('sick_leave_days', 15),
            personal_leave_days=kwargs.get('personal_leave_days', 5),
            notes=kwargs.get('notes'),
        )
        # Set initial balances = entitlements
        emp.annual_leave_balance = emp.annual_leave_days
        emp.sick_leave_balance = emp.sick_leave_days
        emp.personal_leave_balance = emp.personal_leave_days

        db.session.add(emp)
        db.session.commit()
        return emp

    @staticmethod
    def update_employee(emp, **kwargs):
        """Update employee fields"""
        allowed = [
            'department_id', 'position', 'position_ar', 'contract_type',
            'employment_status', 'termination_date', 'termination_reason',
            'base_salary', 'salary_currency', 'payment_frequency',
            'bank_name', 'bank_account_number', 'iban',
            'housing_allowance', 'transport_allowance', 'phone_allowance',
            'other_allowances', 'allowance_notes',
            'national_id', 'passport_number', 'visa_number', 'visa_expiry',
            'date_of_birth', 'gender', 'nationality', 'marital_status',
            'emergency_contact_name', 'emergency_contact_phone',
            'annual_leave_days', 'sick_leave_days', 'personal_leave_days',
            'notes', 'is_active',
        ]
        for field in allowed:
            if field in kwargs and kwargs[field] is not None:
                value = kwargs[field]
                # Convert decimal fields
                if field in ('base_salary', 'housing_allowance', 'transport_allowance',
                             'phone_allowance', 'other_allowances'):
                    value = Decimal(str(value))
                setattr(emp, field, value)

        db.session.commit()
        return emp

    # ---- Leave ----

    @staticmethod
    def request_leave(employee_id, leave_type_id, start_date, end_date, reason='', user_id=None):
        """Submit a leave request"""
        emp = db.get_or_404(Employee, employee_id)
        if emp.employment_status != 'active':
            raise ValueError('الموظف غير نشط')

        lt = db.get_or_404(LeaveType, leave_type_id)

        # Calculate working days (exclude weekends: Fri/Sat for UAE)
        days = HRService._count_working_days(start_date, end_date)
        if days <= 0:
            raise ValueError('يجب أن تكون فترة الإجازةيوم عمل واحد على الأقل')

        # Check balance
        balance = HRService._get_leave_balance(emp, lt)
        if balance < days:
            raise ValueError(
                f'رصيد الإجازة غير كافٍ. الرصيد المتاح: {balance} يوم، '
                f'المطلوب: {days} يوم'
            )

        # Prevent overlapping requests
        overlap = LeaveRequest.query.filter(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status.in_(['pending', 'approved']),
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= start_date,
        ).first()
        if overlap:
            raise ValueError('يوجد طلب إجازة يتقاطع مع هذه الفترة')

        leave = LeaveRequest(
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date=start_date,
            end_date=end_date,
            days=days,
            reason=reason,
        )
        db.session.add(leave)
        db.session.commit()
        return leave

    @staticmethod
    def approve_leave(leave_id, approver_id):
        leave = db.get_or_404(LeaveRequest, leave_id)
        leave.approve(approver_id)
        db.session.commit()
        return leave

    @staticmethod
    def reject_leave(leave_id, approver_id, reason=''):
        leave = db.get_or_404(LeaveRequest, leave_id)
        leave.reject(approver_id, reason)
        db.session.commit()
        return leave

    @staticmethod
    def cancel_leave(leave_id):
        leave = db.get_or_404(LeaveRequest, leave_id)
        leave.cancel()
        db.session.commit()
        return leave

    @staticmethod
    def _get_leave_balance(employee, leave_type):
        if leave_type.code == 'annual':
            return employee.annual_leave_balance or 0
        elif leave_type.code == 'sick':
            return employee.sick_leave_balance or 0
        elif leave_type.code == 'personal':
            return employee.personal_leave_balance or 0
        return 0

    @staticmethod
    def _count_working_days(start, end):
        """Count working days (Sun-Thu for UAE businesses)"""
        count = 0
        current = start
        while current <= end:
            # Friday=4, Saturday=5 in Python
            if current.weekday() not in (4, 5):
                count += 1
            current = date.fromordinal(current.toordinal() + 1)
        return count

    # ---- Payroll ----

    @staticmethod
    def generate_payslip(employee_id, pay_period_start, pay_period_end, pay_date,
                         working_days=22, created_by=None, **adjustments):
        """
        Generate a payslip for one employee.
        working_days = standard working days in the period (default 22 for UAE).
        adjustments: overtime_hours, overtime_rate, bonus, advance_deduction,
                     other_earnings, other_deductions, leave_days_paid, leave_days_unpaid
        """
        emp = db.get_or_404(Employee, employee_id)
        if emp.employment_status != 'active':
            raise ValueError('لا يمكن إنشاء كشف راتب لموظف غير نشط')

        # Check for duplicate
        existing = Payslip.query.filter(
            Payslip.employee_id == employee_id,
            Payslip.pay_period_start == pay_period_start,
            Payslip.pay_period_end == pay_period_end,
            Payslip.status != 'cancelled',
        ).first()
        if existing:
            raise ValueError(f'يوجد كشف راتب بالفعل لهذه الفترة: {existing.payslip_number}')

        # Calculate per-day salary
        base = emp.base_salary or Decimal('0')
        days_in_month = HRService._working_days_in_period(pay_period_start, pay_period_end)
        per_day = (base / Decimal(str(days_in_month))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if days_in_month else Decimal('0')

        # Leave deduction: if unpaid leave
        leave_days_unpaid = Decimal(str(adjustments.get('leave_days_unpaid', 0)))
        leave_deduction = (per_day * leave_days_unpaid).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Overtime
        overtime_hours = Decimal(str(adjustments.get('overtime_hours', 0)))
        overtime_rate = Decimal(str(adjustments.get('overtime_rate', 1.5)))
        # UAE: overtime = (base / 30 / 8) * rate * hours
        hourly_rate = (base / Decimal('30') / Decimal('8')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        overtime_amount = (hourly_rate * overtime_rate * overtime_hours).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Actual worked days
        actual_worked = days_in_month - int(leave_days_unpaid)
        absent_days = max(0, working_days - actual_worked - int(adjustments.get('leave_days_paid', 0)))

        payslip = Payslip(
            payslip_number=generate_number('PAYSLIP', Payslip, 'payslip_number'),
            employee_id=employee_id,
            pay_period_start=pay_period_start,
            pay_period_end=pay_period_end,
            pay_date=pay_date,
            base_salary=base,
            housing_allowance=emp.housing_allowance or Decimal('0'),
            transport_allowance=emp.transport_allowance or Decimal('0'),
            phone_allowance=emp.phone_allowance or Decimal('0'),
            other_earnings=Decimal(str(adjustments.get('other_earnings', 0))),
            overtime_hours=overtime_hours,
            overtime_amount=overtime_amount,
            bonus=Decimal(str(adjustments.get('bonus', 0))),
            leave_deduction=leave_deduction,
            advance_deduction=Decimal(str(adjustments.get('advance_deduction', 0))),
            other_deductions=Decimal(str(adjustments.get('other_deductions', 0))),
            working_days=working_days,
            actual_worked_days=actual_worked,
            leave_days=int(adjustments.get('leave_days_paid', 0)),
            absent_days=absent_days,
            created_by=created_by,
        )
        payslip.calculate_totals()
        db.session.add(payslip)
        db.session.commit()
        return payslip

    @staticmethod
    def generate_bulk_payroll(pay_period_start, pay_period_end, pay_date,
                              working_days=22, created_by=None, adjustments_map=None):
        """
        Generate payslips for all active employees.
        adjustments_map: {employee_id: {overtime_hours, bonus, ...}}
        """
        if adjustments_map is None:
            adjustments_map = {}

        employees = Employee.query.filter_by(is_active=True, employment_status='active').all()
        results = []
        errors = []

        for emp in employees:
            try:
                adj = adjustments_map.get(emp.id, {})
                payslip = HRService.generate_payslip(
                    employee_id=emp.id,
                    pay_period_start=pay_period_start,
                    pay_period_end=pay_period_end,
                    pay_date=pay_date,
                    working_days=working_days,
                    created_by=created_by,
                    **adj,
                )
                results.append(payslip)
            except Exception as e:
                errors.append({
                    'employee': emp.employee_number,
                    'name': emp.user.full_name if emp.user else '?',
                    'error': str(e),
                })

        return {'success_count': len(results), 'error_count': len(errors), 'errors': errors, 'payslips': results}

    @staticmethod
    def _working_days_in_period(start, end):
        """Count working days in a date range (Sun-Thu)"""
        count = 0
        current = start
        while current <= end:
            if current.weekday() not in (4, 5):
                count += 1
            current = date.fromordinal(current.toordinal() + 1)
        return count if count > 0 else 1  # Avoid division by zero

    # ---- Initialize Leave Types ----

    @staticmethod
    def ensure_default_leave_types():
        """Create default leave types if they don't exist"""
        defaults = [
            ('Annual Leave', 'إجازة سنوية', 'annual', 30, True),
            ('Sick Leave', 'إجازة مرضية', 'sick', 15, True),
            ('Personal Leave', 'إجازة شخصية', 'personal', 5, True),
            ('Unpaid Leave', 'إجازة بدون راتب', 'unpaid', 0, False),
            ('Maternity Leave', 'إجازة أمومة', 'maternity', 60, True),
            ('Hajj Leave', 'إجازة حج', 'hajj', 30, True),
        ]
        for name, name_ar, code, days, paid in defaults:
            if not LeaveType.query.filter_by(code=code).first():
                lt = LeaveType(
                    name=name,
                    name_ar=name_ar,
                    code=code,
                    default_days=days,
                    is_paid=paid,
                )
                db.session.add(lt)
        db.session.commit()

    # ---- Dashboard Stats ----

    @staticmethod
    def get_hr_stats():
        """HR dashboard statistics"""
        total = Employee.query.filter_by(is_active=True).count()
        departments = Department.query.filter_by(is_active=True).count()
        pending_leaves = LeaveRequest.query.filter_by(status='pending').count()

        # Upcoming visa expirations (next 90 days)
        from datetime import timedelta
        today = date.today()
        visa_expiry_limit = today + timedelta(days=90)
        expiring_visas = Employee.query.filter(
            Employee.is_active == True,
            Employee.visa_expiry.isnot(None),
            Employee.visa_expiry <= visa_expiry_limit,
            Employee.visa_expiry >= today,
        ).count()

        # Total monthly payroll cost
        from sqlalchemy import func
        total_payroll = db.session.query(
            func.sum(Employee.base_salary + Employee.housing_allowance +
                     Employee.transport_allowance + Employee.phone_allowance +
                     Employee.other_allowances)
        ).filter(
            Employee.is_active == True,
            Employee.employment_status == 'active',
        ).scalar() or Decimal('0')

        return {
            'total_employees': total,
            'active_departments': departments,
            'pending_leaves': pending_leaves,
            'expiring_visas': expiring_visas,
            'total_monthly_payroll': float(total_payroll),
        }
