"""add HR module tables

Revision ID: 3_hr_module
Revises: 2b_add_tenant_scoping
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '3_hr_module'
down_revision = '2b_add_tenant_scoping'
branch_labels = None
depends_on = None


def upgrade():
    # ---- departments ----
    op.create_table(
        'departments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('name_ar', sa.String(100)),
        sa.Column('code', sa.String(20), nullable=False, unique=True),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('departments.id')),
        sa.Column('level', sa.Integer(), server_default='0'),
        sa.Column('manager_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('budget_amount', sa.Numeric(18, 3), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_departments_code', 'departments', ['code'], unique=True)
    op.create_index('ix_departments_active', 'departments', ['is_active'])

    # ---- employees ----
    op.create_table(
        'employees',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('employee_number', sa.String(50), nullable=False, unique=True),
        sa.Column('department_id', sa.Integer(), sa.ForeignKey('departments.id')),
        sa.Column('position', sa.String(100)),
        sa.Column('position_ar', sa.String(100)),
        sa.Column('hire_date', sa.Date(), nullable=False),
        sa.Column('contract_type', sa.String(30), server_default='full_time'),
        sa.Column('employment_status', sa.String(20), server_default='active'),
        sa.Column('termination_date', sa.Date()),
        sa.Column('termination_reason', sa.Text()),
        sa.Column('base_salary', sa.Numeric(15, 3), server_default='0'),
        sa.Column('salary_currency', sa.String(3), server_default='AED'),
        sa.Column('payment_frequency', sa.String(20), server_default='monthly'),
        sa.Column('bank_name', sa.String(100)),
        sa.Column('bank_account_number', sa.String(50)),
        sa.Column('iban', sa.String(50)),
        sa.Column('housing_allowance', sa.Numeric(15, 3), server_default='0'),
        sa.Column('transport_allowance', sa.Numeric(15, 3), server_default='0'),
        sa.Column('phone_allowance', sa.Numeric(15, 3), server_default='0'),
        sa.Column('other_allowances', sa.Numeric(15, 3), server_default='0'),
        sa.Column('allowance_notes', sa.Text()),
        sa.Column('national_id', sa.String(50)),
        sa.Column('passport_number', sa.String(50)),
        sa.Column('visa_number', sa.String(50)),
        sa.Column('visa_expiry', sa.Date()),
        sa.Column('date_of_birth', sa.Date()),
        sa.Column('gender', sa.String(10)),
        sa.Column('nationality', sa.String(50)),
        sa.Column('marital_status', sa.String(20)),
        sa.Column('emergency_contact_name', sa.String(100)),
        sa.Column('emergency_contact_phone', sa.String(20)),
        sa.Column('annual_leave_days', sa.Integer(), server_default='30'),
        sa.Column('sick_leave_days', sa.Integer(), server_default='15'),
        sa.Column('personal_leave_days', sa.Integer(), server_default='5'),
        sa.Column('annual_leave_balance', sa.Integer(), server_default='30'),
        sa.Column('sick_leave_balance', sa.Integer(), server_default='15'),
        sa.Column('personal_leave_balance', sa.Integer(), server_default='5'),
        sa.Column('notes', sa.Text()),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_employees_number', 'employees', ['employee_number'], unique=True)
    op.create_index('ix_employees_department', 'employees', ['department_id'])
    op.create_index('ix_employees_status', 'employees', ['employment_status'])
    op.create_index('ix_employees_active', 'employees', ['is_active'])

    # ---- leave_types ----
    op.create_table(
        'leave_types',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(50), nullable=False, unique=True),
        sa.Column('name_ar', sa.String(50)),
        sa.Column('code', sa.String(20), nullable=False, unique=True),
        sa.Column('default_days', sa.Integer(), server_default='0'),
        sa.Column('is_paid', sa.Boolean(), server_default='1'),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('description', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # ---- leave_requests ----
    op.create_table(
        'leave_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('leave_type_id', sa.Integer(), sa.ForeignKey('leave_types.id'), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('days', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text()),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('approved_at', sa.DateTime()),
        sa.Column('rejection_reason', sa.Text()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_leave_requests_employee', 'leave_requests', ['employee_id'])
    op.create_index('ix_leave_requests_type', 'leave_requests', ['leave_type_id'])
    op.create_index('ix_leave_requests_status', 'leave_requests', ['status'])

    # ---- payslips ----
    op.create_table(
        'payslips',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('payslip_number', sa.String(50), nullable=False, unique=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('pay_period_start', sa.Date(), nullable=False),
        sa.Column('pay_period_end', sa.Date(), nullable=False),
        sa.Column('pay_date', sa.Date(), nullable=False),
        sa.Column('base_salary', sa.Numeric(15, 3), server_default='0'),
        sa.Column('housing_allowance', sa.Numeric(15, 3), server_default='0'),
        sa.Column('transport_allowance', sa.Numeric(15, 3), server_default='0'),
        sa.Column('phone_allowance', sa.Numeric(15, 3), server_default='0'),
        sa.Column('other_earnings', sa.Numeric(15, 3), server_default='0'),
        sa.Column('overtime_hours', sa.Numeric(5, 2), server_default='0'),
        sa.Column('overtime_amount', sa.Numeric(15, 3), server_default='0'),
        sa.Column('bonus', sa.Numeric(15, 3), server_default='0'),
        sa.Column('total_earnings', sa.Numeric(15, 3), server_default='0'),
        sa.Column('leave_deduction', sa.Numeric(15, 3), server_default='0'),
        sa.Column('advance_deduction', sa.Numeric(15, 3), server_default='0'),
        sa.Column('other_deductions', sa.Numeric(15, 3), server_default='0'),
        sa.Column('total_deductions', sa.Numeric(15, 3), server_default='0'),
        sa.Column('net_salary', sa.Numeric(15, 3), server_default='0'),
        sa.Column('working_days', sa.Integer(), server_default='0'),
        sa.Column('actual_worked_days', sa.Integer(), server_default='0'),
        sa.Column('leave_days', sa.Integer(), server_default='0'),
        sa.Column('absent_days', sa.Integer(), server_default='0'),
        sa.Column('status', sa.String(20), server_default='draft'),
        sa.Column('gl_journal_entry_id', sa.Integer(), sa.ForeignKey('gl_journal_entries.id')),
        sa.Column('notes', sa.Text()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('approved_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_payslips_number', 'payslips', ['payslip_number'], unique=True)
    op.create_index('ix_payslips_employee', 'payslips', ['employee_id'])
    op.create_index('ix_payslips_status', 'payslips', ['status'])

    # ---- payslip_lines ----
    op.create_table(
        'payslip_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('payslip_id', sa.Integer(), sa.ForeignKey('payslips.id'), nullable=False),
        sa.Column('line_type', sa.String(20), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('description', sa.String(200)),
        sa.Column('amount', sa.Numeric(15, 3), nullable=False, server_default='0'),
    )
    op.create_index('ix_payslip_lines_payslip', 'payslip_lines', ['payslip_id'])

    # Seed default leave types
    op.execute("""
        INSERT INTO leave_types (name, name_ar, code, default_days, is_paid, is_active) VALUES
        ('Annual Leave', 'إجازة سنوية', 'annual', 30, 1, 1),
        ('Sick Leave', 'إجازة مرضية', 'sick', 15, 1, 1),
        ('Personal Leave', 'إجازة شخصية', 'personal', 5, 1, 1),
        ('Unpaid Leave', 'إجازة بدون راتب', 'unpaid', 0, 0, 1),
        ('Maternity Leave', 'إجازة أمومة', 'maternity', 60, 1, 1),
        ('Hajj Leave', 'إجازة حج', 'hajj', 30, 1, 1)
        ON CONFLICT (code) DO NOTHING;
    """)

    # Seed manage_hr permission
    op.execute("""
        INSERT INTO permissions (code, name, name_ar, category)
        VALUES ('manage_hr', 'Manage HR', 'إدارة الموارد البشرية', 'hr')
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade():
    op.drop_table('payslip_lines')
    op.drop_table('payslips')
    op.drop_table('leave_requests')
    op.drop_table('leave_types')
    op.drop_table('employees')
    op.drop_table('departments')
    op.execute("DELETE FROM permissions WHERE code = 'manage_hr';")
