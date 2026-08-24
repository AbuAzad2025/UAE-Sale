"""
HR Module Routes - Departments, Employees, Leave, Payroll
"""

from datetime import datetime, date
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models.hr import (
    Department, Employee, LeaveType, LeaveRequest, Payslip, PayslipLine,
)
from models import User
from services.hr_service import HRService
from utils.decorators import permission_required, admin_required
from utils.helpers import create_audit_log

hr_bp = Blueprint('hr', __name__, url_prefix='/hr')


# ==================== DASHBOARD ====================

@hr_bp.route('/')
@login_required
@permission_required('manage_hr')
def dashboard():
    """HR Dashboard with key metrics"""
    stats = HRService.get_hr_stats()
    recent_leaves = LeaveRequest.query.order_by(
        LeaveRequest.created_at.desc()
    ).limit(5).all()
    pending_leaves = LeaveRequest.query.filter_by(status='pending').count()
    departments = Department.query.filter_by(is_active=True).all()

    return render_template('hr/dashboard.html',
                         stats=stats,
                         recent_leaves=recent_leaves,
                         pending_leaves=pending_leaves,
                         departments=departments)


# ==================== DEPARTMENTS ====================

@hr_bp.route('/departments')
@login_required
@permission_required('manage_hr')
def departments():
    """List all departments"""
    departments = Department.query.order_by(Department.code).all()
    return render_template('hr/departments.html', departments=departments)


@hr_bp.route('/departments/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_hr')
def create_department():
    if request.method == 'POST':
        try:
            dept = HRService.create_department(
                name=request.form.get('name', '').strip(),
                name_ar=request.form.get('name_ar', '').strip(),
                code=request.form.get('code', '').strip(),
                parent_id=request.form.get('parent_id', type=int),
                manager_id=request.form.get('manager_id', type=int),
                budget=request.form.get('budget_amount', 0, type=float),
            )
            create_audit_log('create', 'departments', dept.id)
            flash(f'✅ تم إنشاء قسم "{dept.name}" بنجاح!', 'success')
            return redirect(url_for('hr.departments'))
        except ValueError as e:
            flash(f'⚠️ {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    parent_depts = Department.query.filter_by(is_active=True).order_by(Department.code).all()
    managers = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    return render_template('hr/create_department.html',
                         parent_departments=parent_depts, managers=managers)


@hr_bp.route('/departments/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_hr')
def edit_department(id):
    dept = db.get_or_404(Department, id)
    if request.method == 'POST':
        try:
            dept.name = request.form.get('name', dept.name)
            dept.name_ar = request.form.get('name_ar', dept.name_ar)
            dept.code = request.form.get('code', dept.code)
            dept.parent_id = request.form.get('parent_id', type=int)
            dept.manager_id = request.form.get('manager_id', type=int)
            dept.budget_amount = request.form.get('budget_amount', dept.budget_amount, type=float)
            dept.description = request.form.get('description', dept.description)
            db.session.commit()
            create_audit_log('update', 'departments', dept.id)
            flash('✅ تم تحديث القسم بنجاح!', 'success')
            return redirect(url_for('hr.departments'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    parent_depts = Department.query.filter(
        Department.is_active == True, Department.id != dept.id
    ).order_by(Department.code).all()
    managers = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    return render_template('hr/edit_department.html', department=dept,
                         parent_departments=parent_depts, managers=managers)


# ==================== EMPLOYEES ====================

@hr_bp.route('/employees')
@login_required
@permission_required('manage_hr')
def employees():
    """List all employees"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    status = request.args.get('status', '', type=str)
    dept_id = request.args.get('department', type=int)

    query = Employee.query

    if search:
        query = query.join(User).filter(
            db.or_(
                User.full_name.ilike(f'%{search}%'),
                User.full_name_ar.ilike(f'%{search}%'),
                Employee.employee_number.ilike(f'%{search}%'),
                User.username.ilike(f'%{search}%'),
            )
        )

    if status:
        query = query.filter_by(employment_status=status)
    else:
        query = query.filter_by(is_active=True)

    if dept_id:
        query = query.filter_by(department_id=dept_id)

    pagination = query.order_by(Employee.employee_number).paginate(
        page=page, per_page=per_page, error_out=False
    )
    departments = Department.query.filter_by(is_active=True).order_by(Department.code).all()

    return render_template('hr/employees.html',
                         employees=pagination.items,
                         pagination=pagination,
                         departments=departments)


@hr_bp.route('/employees/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_hr')
def create_employee():
    if request.method == 'POST':
        try:
            user_id = request.form.get('user_id', type=int)
            if not user_id:
                flash('⚠️ يجب اختيار مستخدم', 'danger')
                return redirect(url_for('hr.create_employee'))

            hire_date_str = request.form.get('hire_date')
            hire_date = datetime.strptime(hire_date_str, '%Y-%m-%d').date() if hire_date_str else date.today()

            visa_expiry = None
            visa_expiry_str = request.form.get('visa_expiry')
            if visa_expiry_str:
                visa_expiry = datetime.strptime(visa_expiry_str, '%Y-%m-%d').date()

            dob = None
            dob_str = request.form.get('date_of_birth')
            if dob_str:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()

            emp = HRService.create_employee(
                user_id=user_id,
                employee_number=request.form.get('employee_number', '').strip(),
                department_id=request.form.get('department_id', type=int),
                position=request.form.get('position', '').strip(),
                hire_date=hire_date,
                base_salary=request.form.get('base_salary', 0, type=float),
                contract_type=request.form.get('contract_type', 'full_time'),
                position_ar=request.form.get('position_ar', '').strip(),
                salary_currency=request.form.get('salary_currency', 'AED'),
                payment_frequency=request.form.get('payment_frequency', 'monthly'),
                bank_name=request.form.get('bank_name'),
                bank_account_number=request.form.get('bank_account_number'),
                iban=request.form.get('iban'),
                housing_allowance=request.form.get('housing_allowance', 0, type=float),
                transport_allowance=request.form.get('transport_allowance', 0, type=float),
                phone_allowance=request.form.get('phone_allowance', 0, type=float),
                other_allowances=request.form.get('other_allowances', 0, type=float),
                national_id=request.form.get('national_id'),
                passport_number=request.form.get('passport_number'),
                visa_number=request.form.get('visa_number'),
                visa_expiry=visa_expiry,
                date_of_birth=dob,
                gender=request.form.get('gender'),
                nationality=request.form.get('nationality'),
                marital_status=request.form.get('marital_status'),
                emergency_contact_name=request.form.get('emergency_contact_name'),
                emergency_contact_phone=request.form.get('emergency_contact_phone'),
                annual_leave_days=request.form.get('annual_leave_days', 30, type=int),
                sick_leave_days=request.form.get('sick_leave_days', 15, type=int),
                personal_leave_days=request.form.get('personal_leave_days', 5, type=int),
                notes=request.form.get('notes'),
            )
            create_audit_log('create', 'employees', emp.id)
            flash(f'✅ تم إضافة الموظف "{emp.user.full_name}" بنجاح!', 'success')
            return redirect(url_for('hr.view_employee', id=emp.id))

        except ValueError as e:
            flash(f'⚠️ {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    # Users not yet employees
    existing_emp_user_ids = [e.user_id for e in Employee.query.all()]
    available_users = User.query.filter(
        User.is_active == True,
        User.is_owner == False,
        ~User.id.in_(existing_emp_user_ids),
    ).order_by(User.full_name).all()

    departments = Department.query.filter_by(is_active=True).order_by(Department.code).all()
    return render_template('hr/create_employee.html',
                         available_users=available_users,
                         departments=departments)


@hr_bp.route('/employees/<int:id>')
@login_required
@permission_required('manage_hr')
def view_employee(id):
    emp = db.get_or_404(Employee, id)
    recent_leaves = LeaveRequest.query.filter_by(employee_id=id).order_by(
        LeaveRequest.created_at.desc()
    ).limit(5).all()
    recent_payslips = Payslip.query.filter_by(employee_id=id).order_by(
        Payslip.pay_period_start.desc()
    ).limit(5).all()

    return render_template('hr/view_employee.html',
                         employee=emp,
                         recent_leaves=recent_leaves,
                         recent_payslips=recent_payslips)


@hr_bp.route('/employees/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_hr')
def edit_employee(id):
    emp = db.get_or_404(Employee, id)
    if request.method == 'POST':
        try:
            visa_expiry = None
            visa_expiry_str = request.form.get('visa_expiry')
            if visa_expiry_str:
                visa_expiry = datetime.strptime(visa_expiry_str, '%Y-%m-%d').date()

            dob = None
            dob_str = request.form.get('date_of_birth')
            if dob_str:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()

            HRService.update_employee(
                emp,
                department_id=request.form.get('department_id', type=int),
                position=request.form.get('position'),
                position_ar=request.form.get('position_ar'),
                contract_type=request.form.get('contract_type'),
                employment_status=request.form.get('employment_status'),
                base_salary=request.form.get('base_salary', 0, type=float),
                salary_currency=request.form.get('salary_currency'),
                payment_frequency=request.form.get('payment_frequency'),
                bank_name=request.form.get('bank_name'),
                bank_account_number=request.form.get('bank_account_number'),
                iban=request.form.get('iban'),
                housing_allowance=request.form.get('housing_allowance', 0, type=float),
                transport_allowance=request.form.get('transport_allowance', 0, type=float),
                phone_allowance=request.form.get('phone_allowance', 0, type=float),
                other_allowances=request.form.get('other_allowances', 0, type=float),
                allowance_notes=request.form.get('allowance_notes'),
                national_id=request.form.get('national_id'),
                passport_number=request.form.get('passport_number'),
                visa_number=request.form.get('visa_number'),
                visa_expiry=visa_expiry,
                date_of_birth=dob,
                gender=request.form.get('gender'),
                nationality=request.form.get('nationality'),
                marital_status=request.form.get('marital_status'),
                emergency_contact_name=request.form.get('emergency_contact_name'),
                emergency_contact_phone=request.form.get('emergency_contact_phone'),
                annual_leave_days=request.form.get('annual_leave_days', 30, type=int),
                sick_leave_days=request.form.get('sick_leave_days', 15, type=int),
                personal_leave_days=request.form.get('personal_leave_days', 5, type=int),
                notes=request.form.get('notes'),
            )
            create_audit_log('update', 'employees', emp.id)
            flash('✅ تم تحديث بيانات الموظف بنجاح!', 'success')
            return redirect(url_for('hr.view_employee', id=emp.id))

        except ValueError as e:
            flash(f'⚠️ {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    departments = Department.query.filter_by(is_active=True).order_by(Department.code).all()
    return render_template('hr/edit_employee.html', employee=emp, departments=departments)


# ==================== LEAVE MANAGEMENT ====================

@hr_bp.route('/leave')
@login_required
@permission_required('manage_hr')
def leave_requests():
    """List all leave requests"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '', type=str)
    emp_id = request.args.get('employee', type=int)

    query = LeaveRequest.query
    if status:
        query = query.filter_by(status=status)
    if emp_id:
        query = query.filter_by(employee_id=emp_id)

    pagination = query.order_by(LeaveRequest.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.employee_number).all()

    return render_template('hr/leave_requests.html',
                         requests=pagination.items,
                         pagination=pagination,
                         employees=employees)


@hr_bp.route('/leave/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_hr')
def create_leave():
    """Create a leave request (for an employee)"""
    if request.method == 'POST':
        try:
            employee_id = request.form.get('employee_id', type=int)
            leave_type_id = request.form.get('leave_type_id', type=int)
            start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
            end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
            reason = request.form.get('reason', '')

            if end_date < start_date:
                flash('⚠️ تاريخ الانتهاء يجب أن يكون بعد تاريخ البداية', 'danger')
                return redirect(url_for('hr.create_leave'))

            leave = HRService.request_leave(
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                start_date=start_date,
                end_date=end_date,
                reason=reason,
                user_id=current_user.id,
            )
            create_audit_log('create', 'leave_requests', leave.id)
            flash('✅ تم تقديم طلب الإجازة بنجاح!', 'success')
            return redirect(url_for('hr.leave_requests'))

        except ValueError as e:
            flash(f'⚠️ {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    employees = Employee.query.filter_by(is_active=True, employment_status='active').order_by(
        Employee.employee_number
    ).all()
    leave_types = LeaveType.query.filter_by(is_active=True).all()
    HRService.ensure_default_leave_types()
    leave_types = LeaveType.query.filter_by(is_active=True).all()

    return render_template('hr/create_leave.html',
                         employees=employees,
                         leave_types=leave_types)


@hr_bp.route('/leave/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('manage_hr')
def approve_leave(id):
    try:
        leave = HRService.approve_leave(id, current_user.id)
        create_audit_log('approve', 'leave_requests', leave.id)
        flash('✅ تمت الموافقة على طلب الإجازة', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('hr.leave_requests'))


@hr_bp.route('/leave/<int:id>/reject', methods=['POST'])
@login_required
@permission_required('manage_hr')
def reject_leave(id):
    try:
        reason = request.form.get('rejection_reason', '')
        leave = HRService.reject_leave(id, current_user.id, reason)
        create_audit_log('reject', 'leave_requests', leave.id)
        flash('⚠️ تم رفض طلب الإجازة', 'warning')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('hr.leave_requests'))


@hr_bp.route('/leave/<int:id>/cancel', methods=['POST'])
@login_required
@permission_required('manage_hr')
def cancel_leave(id):
    try:
        leave = HRService.cancel_leave(id)
        create_audit_log('cancel', 'leave_requests', leave.id)
        flash('✅ تم إلغاء طلب الإجازة', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('hr.leave_requests'))


@hr_bp.route('/leave-types')
@login_required
@permission_required('manage_hr')
def leave_types():
    HRService.ensure_default_leave_types()
    types = LeaveType.query.order_by(LeaveType.code).all()
    return render_template('hr/leave_types.html', leave_types=types)


# ==================== PAYROLL ====================

@hr_bp.route('/payroll')
@login_required
@permission_required('manage_hr')
def payroll():
    """List all payslips"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '', type=str)
    emp_id = request.args.get('employee', type=int)

    query = Payslip.query
    if status:
        query = query.filter_by(status=status)
    if emp_id:
        query = query.filter_by(employee_id=emp_id)

    pagination = query.order_by(Payslip.pay_period_start.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.employee_number).all()

    return render_template('hr/payroll.html',
                         payslips=pagination.items,
                         pagination=pagination,
                         employees=employees)


@hr_bp.route('/payroll/generate', methods=['GET', 'POST'])
@login_required
@permission_required('manage_hr')
def generate_payroll():
    """Generate payroll for all active employees"""
    if request.method == 'POST':
        try:
            period_start = datetime.strptime(request.form.get('period_start'), '%Y-%m-%d').date()
            period_end = datetime.strptime(request.form.get('period_end'), '%Y-%m-%d').date()
            pay_date = datetime.strptime(request.form.get('pay_date'), '%Y-%m-%d').date()
            working_days = request.form.get('working_days', 22, type=int)

            if period_end < period_start:
                flash('⚠️ تاريخ النهاية يجب أن يكون بعد تاريخ البداية', 'danger')
                return redirect(url_for('hr.generate_payroll'))

            result = HRService.generate_bulk_payroll(
                pay_period_start=period_start,
                pay_period_end=period_end,
                pay_date=pay_date,
                working_days=working_days,
                created_by=current_user.id,
            )

            if result['success_count'] > 0:
                flash(f'✅ تم إنشاء {result["success_count"]} كشف راتب بنجاح!', 'success')
            if result['error_count'] > 0:
                error_msgs = [f'{e["employee"]}: {e["error"]}' for e in result['errors']]
                flash(f'⚠️ فشل إنشاء {result["error_count"]} كشف راتب:<br>' +
                      '<br>'.join(error_msgs), 'warning')

            return redirect(url_for('hr.payroll'))

        except Exception as e:
            flash(f'❌ خطأ: {str(e)}', 'danger')

    return render_template('hr/generate_payroll.html')


@hr_bp.route('/payroll/<int:id>')
@login_required
@permission_required('manage_hr')
def view_payslip(id):
    payslip = db.get_or_404(Payslip, id)
    return render_template('hr/view_payslip.html', payslip=payslip)


@hr_bp.route('/payroll/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('manage_hr')
def approve_payslip(id):
    try:
        payslip = db.get_or_404(Payslip, id)
        payslip.approve(current_user.id)
        db.session.commit()
        create_audit_log('approve', 'payslips', payslip.id)
        flash('✅ تم اعتماد كشف الرواتب بنجاح', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('hr.view_payslip', id=id))


@hr_bp.route('/payroll/<int:id>/pay', methods=['POST'])
@login_required
@permission_required('manage_hr')
def mark_payslip_paid(id):
    try:
        payslip = db.get_or_404(Payslip, id)
        payslip.mark_paid()
        db.session.commit()
        create_audit_log('pay', 'payslips', payslip.id)
        flash('✅ تم تسجيل الدفع بنجاح', 'success')
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('hr.view_payslip', id=id))


# ==================== API ====================

@hr_bp.route('/api/employee/<int:id>/leave-balance')
@login_required
@permission_required('manage_hr')
def api_leave_balance(id):
    """Get employee leave balance"""
    emp = db.get_or_404(Employee, id)
    return jsonify({
        'employee_number': emp.employee_number,
        'annual': emp.annual_leave_balance,
        'sick': emp.sick_leave_balance,
        'personal': emp.personal_leave_balance,
        'total': emp.total_annual_leave,
    })


@hr_bp.route('/api/employees')
@login_required
@permission_required('manage_hr')
def api_employees():
    """List employees for AJAX"""
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.employee_number).all()
    return jsonify([e.to_dict() for e in employees])
