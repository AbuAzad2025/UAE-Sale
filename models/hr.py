"""
HR Module Models - Human Resources & Payroll Management
"""

from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP
from extensions import db


class Department(db.Model):
    """Organizational department"""
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    name_ar = db.Column(db.String(100))
    code = db.Column(db.String(20), unique=True, nullable=False)

    # Hierarchy
    parent_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    level = db.Column(db.Integer, default=0)

    # Manager
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Budget
    budget_amount = db.Column(db.Numeric(18, 3), default=0)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    description = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    parent = db.relationship('Department', remote_side=[id], backref='children')
    manager = db.relationship('User', foreign_keys=[manager_id])
    employees = db.relationship('Employee', back_populates='department', lazy='dynamic')

    def __repr__(self):
        return f'<Department {self.code} - {self.name}>'

    @property
    def full_name(self):
        return f"{self.code} - {self.name_ar or self.name}"

    @property
    def employee_count(self):
        return self.employees.filter_by(is_active=True).count()

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'name_ar': self.name_ar,
            'code': self.code,
            'manager': self.manager.full_name if self.manager else None,
            'employee_count': self.employee_count,
            'is_active': self.is_active,
        }


class Employee(db.Model):
    """
    Employee profile - linked 1:1 with User.
    Contains all HR-specific data not in the User model.
    """
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    employee_number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Department & Position
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), index=True)
    position = db.Column(db.String(100))  # Job title
    position_ar = db.Column(db.String(100))

    # Employment Details
    hire_date = db.Column(db.Date, nullable=False)
    contract_type = db.Column(db.String(30), default='full_time')  # full_time, part_time, contract, intern
    employment_status = db.Column(db.String(20), default='active', index=True)  # active, on_leave, terminated, resigned
    termination_date = db.Column(db.Date)
    termination_reason = db.Column(db.Text)

    # Salary & Compensation
    base_salary = db.Column(db.Numeric(15, 3), nullable=False, default=0)
    salary_currency = db.Column(db.String(3), default='AED')
    payment_frequency = db.Column(db.String(20), default='monthly')  # monthly, bi_weekly, weekly
    bank_name = db.Column(db.String(100))
    bank_account_number = db.Column(db.String(50))
    iban = db.Column(db.String(50))

    # Allowances (monthly)
    housing_allowance = db.Column(db.Numeric(15, 3), default=0)
    transport_allowance = db.Column(db.Numeric(15, 3), default=0)
    phone_allowance = db.Column(db.Numeric(15, 3), default=0)
    other_allowances = db.Column(db.Numeric(15, 3), default=0)
    allowance_notes = db.Column(db.Text)

    # Personal Info
    national_id = db.Column(db.String(50))
    passport_number = db.Column(db.String(50))
    visa_number = db.Column(db.String(50))
    visa_expiry = db.Column(db.Date)
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(10))  # male, female
    nationality = db.Column(db.String(50))
    marital_status = db.Column(db.String(20))  # single, married, divorced, widowed
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(20))

    # Leave Balance (annual)
    annual_leave_days = db.Column(db.Integer, default=30)
    sick_leave_days = db.Column(db.Integer, default=15)
    personal_leave_days = db.Column(db.Integer, default=5)

    # Current balances (updated when leave is approved)
    annual_leave_balance = db.Column(db.Integer, default=30)
    sick_leave_balance = db.Column(db.Integer, default=15)
    personal_leave_balance = db.Column(db.Integer, default=5)

    # Meta
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', backref=db.backref('employee_profile', uselist=False))
    department = db.relationship('Department', back_populates='employees')
    leave_requests = db.relationship('LeaveRequest', back_populates='employee', lazy='dynamic')
    payslips = db.relationship('Payslip', back_populates='employee', lazy='dynamic')

    def __repr__(self):
        return f'<Employee {self.employee_number}>'

    @property
    def total_monthly_compensation(self):
        """Total monthly cost to company"""
        base = self.base_salary or Decimal('0')
        allowances = (
            (self.housing_allowance or Decimal('0')) +
            (self.transport_allowance or Decimal('0')) +
            (self.phone_allowance or Decimal('0')) +
            (self.other_allowances or Decimal('0'))
        )
        return base + allowances

    @property
    def total_annual_leave(self):
        return (self.annual_leave_balance or 0) + (self.sick_leave_balance or 0) + (self.personal_leave_balance or 0)

    @property
    def total_leave_entitlement(self):
        return (self.annual_leave_days or 0) + (self.sick_leave_days or 0) + (self.personal_leave_days or 0)

    @property
    def years_of_service(self):
        if not self.hire_date:
            return 0
        today = date.today()
        years = today.year - self.hire_date.year
        if (today.month, today.day) < (self.hire_date.month, self.hire_date.day):
            years -= 1
        return max(0, years)

    def to_dict(self):
        return {
            'id': self.id,
            'employee_number': self.employee_number,
            'user_id': self.user_id,
            'full_name': self.user.full_name if self.user else None,
            'full_name_ar': self.user.full_name_ar if self.user else None,
            'email': self.user.email if self.user else None,
            'phone': self.user.phone if self.user else None,
            'department': self.department.name if self.department else None,
            'position': self.position,
            'hire_date': self.hire_date.isoformat() if self.hire_date else None,
            'employment_status': self.employment_status,
            'base_salary': float(self.base_salary) if self.base_salary else 0,
            'is_active': self.is_active,
        }


class LeaveType(db.Model):
    """Leave type definition"""
    __tablename__ = 'leave_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    name_ar = db.Column(db.String(50))
    code = db.Column(db.String(20), unique=True, nullable=False)
    default_days = db.Column(db.Integer, default=0)
    is_paid = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    leave_requests = db.relationship('LeaveRequest', back_populates='leave_type', lazy='dynamic')

    def __repr__(self):
        return f'<LeaveType {self.code} - {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'name_ar': self.name_ar,
            'code': self.code,
            'default_days': self.default_days,
            'is_paid': self.is_paid,
        }


class LeaveRequest(db.Model):
    """Employee leave request"""
    __tablename__ = 'leave_requests'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=False, index=True)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    days = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text)

    status = db.Column(db.String(20), default='pending', index=True)  # pending, approved, rejected, cancelled

    # Approval
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)

    # Backfill coverage
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    employee = db.relationship('Employee', back_populates='leave_requests')
    leave_type = db.relationship('LeaveType', back_populates='leave_requests')
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])

    def __repr__(self):
        return f'<LeaveRequest {self.employee.employee_number if self.employee else "?"} - {self.status}>'

    @property
    def status_ar(self):
        statuses = {
            'pending': 'قيد المراجعة',
            'approved': 'تمت الموافقة',
            'rejected': 'مرفوض',
            'cancelled': 'ملغي',
        }
        return statuses.get(self.status, self.status)

    @property
    def status_badge(self):
        badges = {
            'pending': 'warning',
            'approved': 'success',
            'rejected': 'danger',
            'cancelled': 'secondary',
        }
        return badges.get(self.status, 'secondary')

    def approve(self, user_id):
        if self.status != 'pending':
            raise ValueError('طلب الإجازة ليس قيد المراجعة')
        self.status = 'approved'
        self.approved_by_id = user_id
        self.approved_at = datetime.now(timezone.utc)
        # Deduct from balance
        self._adjust_balance(-self.days)

    def reject(self, user_id, reason=''):
        if self.status != 'pending':
            raise ValueError('طلب الإجازة ليس قيد المراجعة')
        self.status = 'rejected'
        self.approved_by_id = user_id
        self.approved_at = datetime.now(timezone.utc)
        self.rejection_reason = reason

    def cancel(self):
        if self.status == 'approved':
            # Restore balance
            self._adjust_balance(self.days)
        self.status = 'cancelled'

    def _adjust_balance(self, days):
        """Adjust employee leave balance based on leave type"""
        emp = self.employee
        if not emp:
            return
        lt = self.leave_type
        if not lt:
            return
        if lt.code == 'annual':
            emp.annual_leave_balance = (emp.annual_leave_balance or 0) + days
        elif lt.code == 'sick':
            emp.sick_leave_balance = (emp.sick_leave_balance or 0) + days
        elif lt.code == 'personal':
            emp.personal_leave_balance = (emp.personal_leave_balance or 0) + days

    def to_dict(self):
        return {
            'id': self.id,
            'employee': self.employee.employee_number if self.employee else None,
            'leave_type': self.leave_type.name if self.leave_type else None,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'days': self.days,
            'status': self.status,
            'status_ar': self.status_ar,
            'reason': self.reason,
        }


class Payslip(db.Model):
    """Monthly payslip for an employee"""
    __tablename__ = 'payslips'

    id = db.Column(db.Integer, primary_key=True)
    payslip_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)

    # Period
    pay_period_start = db.Column(db.Date, nullable=False)
    pay_period_end = db.Column(db.Date, nullable=False)
    pay_date = db.Column(db.Date, nullable=False)

    # Earnings
    base_salary = db.Column(db.Numeric(15, 3), default=0)
    housing_allowance = db.Column(db.Numeric(15, 3), default=0)
    transport_allowance = db.Column(db.Numeric(15, 3), default=0)
    phone_allowance = db.Column(db.Numeric(15, 3), default=0)
    other_earnings = db.Column(db.Numeric(15, 3), default=0)
    overtime_hours = db.Column(db.Numeric(5, 2), default=0)
    overtime_amount = db.Column(db.Numeric(15, 3), default=0)
    bonus = db.Column(db.Numeric(15, 3), default=0)
    total_earnings = db.Column(db.Numeric(15, 3), default=0)

    # Deductions
    leave_deduction = db.Column(db.Numeric(15, 3), default=0)
    advance_deduction = db.Column(db.Numeric(15, 3), default=0)
    other_deductions = db.Column(db.Numeric(15, 3), default=0)
    total_deductions = db.Column(db.Numeric(15, 3), default=0)

    # Net
    net_salary = db.Column(db.Numeric(15, 3), default=0)

    # Days
    working_days = db.Column(db.Integer, default=0)
    actual_worked_days = db.Column(db.Integer, default=0)
    leave_days = db.Column(db.Integer, default=0)
    absent_days = db.Column(db.Integer, default=0)

    # Status
    status = db.Column(db.String(20), default='draft', index=True)  # draft, approved, paid, cancelled

    # GL Integration
    gl_journal_entry_id = db.Column(db.Integer, db.ForeignKey('gl_journal_entries.id'))

    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    employee = db.relationship('Employee', back_populates='payslips')
    lines = db.relationship('PayslipLine', back_populates='payslip', cascade='all, delete-orphan')
    creator = db.relationship('User', foreign_keys=[created_by])
    approver = db.relationship('User', foreign_keys=[approved_by])

    def __repr__(self):
        return f'<Payslip {self.payslip_number}>'

    @property
    def status_ar(self):
        statuses = {
            'draft': 'مسودة',
            'approved': 'معتمدة',
            'paid': 'مدفوعة',
            'cancelled': 'ملغاة',
        }
        return statuses.get(self.status, self.status)

    @property
    def status_badge(self):
        badges = {
            'draft': 'secondary',
            'approved': 'info',
            'paid': 'success',
            'cancelled': 'danger',
        }
        return badges.get(self.status, 'secondary')

    def calculate_totals(self):
        """Recalculate all totals from components"""
        self.total_earnings = (
            (self.base_salary or Decimal('0')) +
            (self.housing_allowance or Decimal('0')) +
            (self.transport_allowance or Decimal('0')) +
            (self.phone_allowance or Decimal('0')) +
            (self.other_earnings or Decimal('0')) +
            (self.overtime_amount or Decimal('0')) +
            (self.bonus or Decimal('0'))
        )
        self.total_deductions = (
            (self.leave_deduction or Decimal('0')) +
            (self.advance_deduction or Decimal('0')) +
            (self.other_deductions or Decimal('0'))
        )
        self.net_salary = (self.total_earnings - self.total_deductions).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    def approve(self, user_id):
        if self.status != 'draft':
            raise ValueError('يمكن اعتماد كشوفات الرواتب في حالة مسودة فقط')
        self.status = 'approved'
        self.approved_by = user_id

    def mark_paid(self):
        if self.status != 'approved':
            raise ValueError('يجب اعتماد الكشف قبل تسجيل الدفع')
        self.status = 'paid'

    def to_dict(self):
        return {
            'id': self.id,
            'payslip_number': self.payslip_number,
            'employee': self.employee.employee_number if self.employee else None,
            'employee_name': self.employee.user.full_name if self.employee and self.employee.user else None,
            'pay_period': f'{self.pay_period_start} - {self.pay_period_end}',
            'total_earnings': float(self.total_earnings) if self.total_earnings else 0,
            'total_deductions': float(self.total_deductions) if self.total_deductions else 0,
            'net_salary': float(self.net_salary) if self.net_salary else 0,
            'status': self.status,
            'status_ar': self.status_ar,
        }


class PayslipLine(db.Model):
    """Additional payslip line items (bonuses, deductions, adjustments)"""
    __tablename__ = 'payslip_lines'

    id = db.Column(db.Integer, primary_key=True)
    payslip_id = db.Column(db.Integer, db.ForeignKey('payslips.id'), nullable=False, index=True)

    line_type = db.Column(db.String(20), nullable=False)  # earning, deduction
    category = db.Column(db.String(50), nullable=False)   # overtime, bonus, advance, loan, penalty, etc.
    description = db.Column(db.String(200))
    amount = db.Column(db.Numeric(15, 3), nullable=False, default=0)

    payslip = db.relationship('Payslip', back_populates='lines')

    def __repr__(self):
        return f'<PayslipLine {self.category} {self.amount}>'
