from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from extensions import db, csrf
from models import GLAccount, GLJournalEntry, GLJournalLine, Cheque, PaymentVault
from services.gl_service import GLService
from services.cash_flow_service import CashFlowService
from services.aging_analysis_service import AgingAnalysisService
from utils.decorators import admin_required, permission_required
from utils.helpers import create_audit_log
from decimal import Decimal
from datetime import datetime, date, timedelta

ledger_bp = Blueprint('ledger', __name__, url_prefix='/ledger')


@ledger_bp.route('/')
@login_required
@permission_required('view_ledger')
def index():
    accounts = GLAccount.query.filter_by(is_active=True).order_by(GLAccount.code).all()
    return render_template('ledger/index.html', accounts=accounts)


@ledger_bp.route('/account/<int:id>')
@login_required
@permission_required('view_ledger')
def account_ledger(id):
    account = GLAccount.query.get_or_404(id)
    
    date_from = request.args.get('date_from', type=str)
    date_to = request.args.get('date_to', type=str)
    
    query = GLJournalLine.query.filter_by(account_id=id).join(GLJournalEntry)
    
    if date_from:
        query = query.filter(func.date(GLJournalEntry.entry_date) >= date_from)
    
    if date_to:
        query = query.filter(func.date(GLJournalEntry.entry_date) <= date_to)
    
    lines = query.order_by(GLJournalEntry.entry_date).all()
    
    running_balance = Decimal('0')
    transactions = []
    
    for line in lines:
        running_balance += line.debit - line.credit
        
        transactions.append({
            'date': line.entry.entry_date,
            'entry_number': line.entry.entry_number,
            'description': line.description or line.entry.description,
            'reference': f'{line.entry.reference_type} #{line.entry.reference_id}' if line.entry.reference_type else '',
            'debit': float(line.debit),
            'credit': float(line.credit),
            'balance': float(running_balance)
        })
    
    summary = {
        'total_debit': sum(t['debit'] for t in transactions),
        'total_credit': sum(t['credit'] for t in transactions),
        'final_balance': float(running_balance)
    }
    
    return render_template('ledger/account_ledger.html',
                         account=account,
                         transactions=transactions,
                         summary=summary)


@ledger_bp.route('/trial-balance')
@login_required
@permission_required('view_ledger')
def trial_balance():
    accounts = GLAccount.query.filter_by(is_active=True).order_by(GLAccount.code).all()
    
    trial_data = []
    total_debit = Decimal('0')
    total_credit = Decimal('0')
    
    for account in accounts:
        debit_sum = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=account.id).scalar() or Decimal('0')
        credit_sum = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=account.id).scalar() or Decimal('0')
        
        balance = debit_sum - credit_sum
        
        if balance != 0 or debit_sum != 0 or credit_sum != 0:
            trial_data.append({
                'account': account,
                'debit': float(debit_sum),
                'credit': float(credit_sum),
                'balance': float(balance)
            })
            
            total_debit += debit_sum
            total_credit += credit_sum
    
    is_balanced = (total_debit == total_credit)
    
    return render_template('ledger/trial_balance.html',
                         trial_data=trial_data,
                         total_debit=float(total_debit),
                         total_credit=float(total_credit),
                         is_balanced=is_balanced)


@ledger_bp.route('/journal-entries')
@login_required
@permission_required('view_ledger')
def journal_entries():
    page = request.args.get('page', 1, type=int)
    
    pagination = GLJournalEntry.query.order_by(GLJournalEntry.entry_date.desc()).paginate(
        page=page,
        per_page=50,
        error_out=False
    )
    
    return render_template('ledger/journal_entries.html',
                         entries=pagination.items,
                         pagination=pagination)


@ledger_bp.route('/income-statement')
@login_required
@permission_required('view_ledger')
def income_statement():
    date_from = request.args.get('date_from', type=str)
    date_to = request.args.get('date_to', type=str)
    
    revenue_accounts = GLAccount.query.filter(GLAccount.code.like('4%')).all()
    expense_accounts = GLAccount.query.filter(GLAccount.code.like('5%')).all()
    expense_accounts += GLAccount.query.filter(GLAccount.code.like('6%')).all()
    
    revenues = {}
    total_revenue = Decimal('0')
    
    for acc in revenue_accounts:
        credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        balance = credit - debit
        
        if balance > 0:
            revenues[acc.name] = float(balance)
            total_revenue += balance
    
    expenses = {}
    total_expense = Decimal('0')
    
    for acc in expense_accounts:
        debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        balance = debit - credit
        
        if balance > 0:
            expenses[acc.name] = float(balance)
            total_expense += balance
    
    net_profit = total_revenue - total_expense
    
    return render_template('ledger/income_statement.html',
                         revenues=revenues,
                         expenses=expenses,
                         total_revenue=float(total_revenue),
                         total_expense=float(total_expense),
                         net_profit=float(net_profit))


@ledger_bp.route('/balance-sheet')
@login_required
@permission_required('view_ledger')
def balance_sheet():
    assets = {}
    liabilities = {}
    equity = {}
    
    asset_accounts = GLAccount.query.filter(GLAccount.code.like('1%')).all()
    liability_accounts = GLAccount.query.filter(GLAccount.code.like('2%')).all()
    equity_accounts = GLAccount.query.filter(GLAccount.code.like('3%')).all()
    
    total_assets = Decimal('0')
    for acc in asset_accounts:
        debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        balance = debit - credit
        
        if balance != 0:
            assets[acc.name] = float(balance)
            total_assets += balance
    
    total_liabilities = Decimal('0')
    for acc in liability_accounts:
        credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        balance = credit - debit
        
        if balance != 0:
            liabilities[acc.name] = float(balance)
            total_liabilities += balance
    
    total_equity = Decimal('0')
    for acc in equity_accounts:
        credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=acc.id).scalar() or Decimal('0')
        balance = credit - debit
        
        if balance != 0:
            equity[acc.name] = float(balance)
            total_equity += balance
    
    return render_template('ledger/balance_sheet.html',
                         assets=assets,
                         liabilities=liabilities,
                         equity=equity,
                         total_assets=float(total_assets),
                         total_liabilities=float(total_liabilities),
                         total_equity=float(total_equity))


@ledger_bp.route('/accounts-tree')
@login_required
@permission_required('view_ledger')
def accounts_tree():
    """عرض شجرة الحسابات"""
    tree = GLService.get_accounts_tree()
    return render_template('ledger/accounts_tree.html', accounts_tree=tree)


@ledger_bp.route('/account/<int:id>/statement')
@login_required
@permission_required('view_ledger')
def account_statement(id):
    """كشف حساب تفصيلي"""
    date_from = request.args.get('date_from', type=str)
    date_to = request.args.get('date_to', type=str)
    
    statement = GLService.get_account_statement(id, date_from, date_to)
    
    return render_template('ledger/account_statement.html',
                         statement=statement,
                         date_from=date_from,
                         date_to=date_to)


@ledger_bp.route('/manual-entry', methods=['GET', 'POST'])
@login_required
@permission_required('manage_ledger')
def manual_entry():
    """إضافة قيد يدوي"""
    if request.method == 'POST':
        try:
            description = request.form.get('description')
            entry_date = request.form.get('entry_date')
            notes = request.form.get('notes')
            
            # تحويل التاريخ
            if entry_date:
                entry_date = datetime.strptime(entry_date, '%Y-%m-%d')
            
            # جمع السطور
            lines = []
            
            # جمع جميع السطور من الفورم
            i = 0
            while True:
                account_code = request.form.get(f'line_{i}_account')
                if not account_code:
                    break
                
                debit = request.form.get(f'line_{i}_debit', 0)
                credit = request.form.get(f'line_{i}_credit', 0)
                line_description = request.form.get(f'line_{i}_description', '')
                
                # تحويل القيم الفارغة إلى صفر
                try:
                    debit_value = float(debit) if debit and debit.strip() else 0
                    credit_value = float(credit) if credit and credit.strip() else 0
                except (ValueError, AttributeError):
                    debit_value = 0
                    credit_value = 0
                
                # إضافة السطر فقط إذا كان فيه قيمة
                if debit_value > 0 or credit_value > 0:
                    lines.append({
                        'account_code': account_code,
                        'debit': debit_value,
                        'credit': credit_value,
                        'description': line_description
                    })
                
                i += 1
            
            # إنشاء القيد
            entry = GLService.create_manual_entry(
                description=description,
                lines=lines,
                entry_date=entry_date,
                notes=notes,
                created_by=current_user.id
            )
            
            create_audit_log('create', 'gl_journal_entries', entry.id)
            
            flash(f'✅ تم إنشاء القيد {entry.entry_number} بنجاح', 'success')
            return redirect(url_for('ledger.view_entry', id=entry.id))
        
        except ValueError as e:
            flash(f'❌ خطأ: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
    
    # الحصول على الحسابات النشطة (غير رئيسية)
    accounts = GLAccount.query.filter_by(is_active=True, is_header=False).order_by(GLAccount.code).all()
    
    return render_template('ledger/manual_entry.html', accounts=accounts, today=date.today())


@ledger_bp.route('/entry/<int:id>')
@login_required
@permission_required('view_ledger')
def view_entry(id):
    """عرض تفاصيل القيد"""
    entry = GLJournalEntry.query.get_or_404(id)
    lines = entry.lines.all()
    
    return render_template('ledger/view_entry.html', entry=entry, lines=lines)


@ledger_bp.route('/entry/<int:id>/reverse', methods=['POST'])
@login_required
@permission_required('manage_ledger')
def reverse_entry(id):
    """عكس القيد"""
    try:
        entry = GLJournalEntry.query.get_or_404(id)
        
        description = request.form.get('description')
        reversed_entry = entry.reverse_entry(description)
        
        db.session.commit()
        
        create_audit_log('create', 'gl_journal_entries', reversed_entry.id, 
                        changes={'reversed_from': entry.entry_number})
        
        flash(f'✅ تم عكس القيد بنجاح - القيد الجديد: {reversed_entry.entry_number}', 'success')
        return redirect(url_for('ledger.view_entry', id=reversed_entry.id))
    
    except ValueError as e:
        flash(f'❌ خطأ: {str(e)}', 'danger')
        return redirect(url_for('ledger.view_entry', id=id))
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
        return redirect(url_for('ledger.view_entry', id=id))


@ledger_bp.route('/api/accounts/search')
@login_required
@permission_required('view_ledger')
def api_search_accounts():
    """API للبحث عن الحسابات"""
    query = request.args.get('q', '').strip()
    
    accounts = GLAccount.query.filter(
        GLAccount.is_active == True,
        GLAccount.is_header == False,
        db.or_(
            GLAccount.code.ilike(f'%{query}%'),
            GLAccount.name.ilike(f'%{query}%'),
            GLAccount.name_ar.ilike(f'%{query}%')
        )
    ).order_by(GLAccount.code).limit(20).all()
    
    return jsonify([{
        'id': acc.id,
        'code': acc.code,
        'name': acc.name,
        'name_ar': acc.name_ar,
        'full_name': acc.full_name,
        'type': acc.type,
        'balance': float(acc.get_balance())
    } for acc in accounts])


@ledger_bp.route('/api/calculate-journal-balance', methods=['POST'])
def api_calculate_journal_balance():
    """API لحساب توازن القيد اليدوي - Backend Calculation"""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        lines = data.get('lines', [])
        
        total_debit = Decimal('0')
        total_credit = Decimal('0')
        
        for line in lines:
            debit = Decimal(str(line.get('debit', 0) or 0))
            credit = Decimal(str(line.get('credit', 0) or 0))
            total_debit += debit
            total_credit += credit
        
        difference = abs(total_debit - total_credit)
        is_balanced = difference < Decimal('0.01') and total_debit > 0 and total_credit > 0
        
        return jsonify({
            'success': True,
            'total_debit': float(total_debit),
            'total_credit': float(total_credit),
            'difference': float(difference),
            'is_balanced': is_balanced
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@ledger_bp.route('/cash-flow')
@login_required
@permission_required('view_ledger')
def cash_flow():
    """قائمة التدفقات النقدية"""
    # الحصول على الفترة (آخر شهر افتراضياً)
    today = date.today()
    default_start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    default_end = today.strftime('%Y-%m-%d')
    
    date_from = request.args.get('date_from', default_start, type=str)
    date_to = request.args.get('date_to', default_end, type=str)
    
    try:
        report = CashFlowService.generate_cash_flow(date_from, date_to)
        
        return render_template('ledger/cash_flow.html',
                             report=report,
                             date_from=date_from,
                             date_to=date_to)
    except Exception as e:
        flash(f'❌ خطأ في إنشاء قائمة التدفقات: {str(e)}', 'danger')
        return redirect(url_for('ledger.index'))


@ledger_bp.route('/aging-analysis')
@login_required
@permission_required('view_ledger')
def aging_analysis():
    """تحليل عمر الذمم"""
    analysis_type = request.args.get('type', 'receivables', type=str)  # receivables or payables
    as_of_date = request.args.get('as_of_date', type=str)
    
    try:
        if analysis_type == 'receivables':
            report = AgingAnalysisService.get_receivables_aging(as_of_date)
            title = 'تحليل عمر الذمم المدينة'
        else:
            report = AgingAnalysisService.get_payables_aging(as_of_date)
            title = 'تحليل عمر الذمم الدائنة'
        
        return render_template('ledger/aging_analysis.html',
                             report=report,
                             analysis_type=analysis_type,
                             title=title,
                             as_of_date=as_of_date or date.today().strftime('%Y-%m-%d'))
    except Exception as e:
        flash(f'❌ خطأ في إنشاء تحليل العمر: {str(e)}', 'danger')
        return redirect(url_for('ledger.index'))

# ==================== لوحة التحكم الإدارية ====================

@ledger_bp.route('/admin-dashboard')
@login_required
@permission_required('admin')
def admin_dashboard():
    """لوحة تحكم شاملة لدفتر الأستاذ"""
    
    # إحصائيات عامة
    total_accounts = GLAccount.query.count()
    active_accounts = GLAccount.query.filter_by(is_active=True).count()
    total_entries = GLJournalEntry.query.count()
    posted_entries = GLJournalEntry.query.filter_by(is_posted=True).count()
    
    # إحصائيات مالية
    cash_accounts = GLAccount.query.filter(GLAccount.code.like('11%')).all()
    total_cash = sum(account.get_balance() for account in cash_accounts)
    
    # آخر القيود
    recent_entries = GLJournalEntry.query.order_by(GLJournalEntry.created_at.desc()).limit(10).all()
    
    # الحسابات ذات الأرصدة العالية
    high_balance_accounts = []
    for account in GLAccount.query.filter_by(is_active=True, is_header=False).all():
        balance = account.get_balance()
        if abs(balance) > 1000:  # أرصدة أعلى من 1000
            high_balance_accounts.append({
                'account': account,
                'balance': balance
            })
    
    # ترتيب حسب الرصيد
    high_balance_accounts.sort(key=lambda x: abs(x['balance']), reverse=True)
    
    # إحصائيات الشيكات
    total_cheques = Cheque.query.count()
    pending_cheques = Cheque.query.filter_by(status='pending').count()
    cleared_cheques = Cheque.query.filter_by(status='cleared').count()
    
    # إحصائيات المحافظ
    total_vaults = PaymentVault.query.count()
    active_vaults = PaymentVault.query.filter_by(is_locked=False).count()
    
    return render_template('admin/ledger/dashboard.html',
                         total_accounts=total_accounts,
                         active_accounts=active_accounts,
                         total_entries=total_entries,
                         posted_entries=posted_entries,
                         total_cash=total_cash,
                         recent_entries=recent_entries,
                         high_balance_accounts=high_balance_accounts[:10],
                         total_cheques=total_cheques,
                         pending_cheques=pending_cheques,
                         cleared_cheques=cleared_cheques,
                         total_vaults=total_vaults,
                         active_vaults=active_vaults)

@ledger_bp.route('/admin-accounts')
@login_required
@permission_required('admin')
def admin_accounts():
    """إدارة الحسابات المحاسبية"""
    accounts = GLAccount.query.order_by(GLAccount.code).all()
    return render_template('admin/ledger/accounts.html', accounts=accounts)

@ledger_bp.route('/admin-accounts/add', methods=['GET', 'POST'])
@login_required
@permission_required('admin')
def admin_add_account():
    """إضافة حساب محاسبي جديد"""
    if request.method == 'POST':
        try:
            code = request.form.get('code')
            name = request.form.get('name')
            name_ar = request.form.get('name_ar')
            account_type = request.form.get('type')
            parent_id = request.form.get('parent_id') or None
            currency = request.form.get('currency', 'AED')
            is_header = bool(request.form.get('is_header'))
            description = request.form.get('description')
            
            # التحقق من عدم تكرار الكود
            existing = GLAccount.query.filter_by(code=code).first()
            if existing:
                flash('❌ كود الحساب موجود مسبقاً', 'danger')
                return redirect(url_for('ledger.admin_add_account'))
            
            # حساب المستوى
            level = 0
            if parent_id:
                parent = GLAccount.query.get(parent_id)
                level = parent.level + 1 if parent else 0
            
            account = GLAccount(
                code=code,
                name=name,
                name_ar=name_ar,
                type=account_type,
                parent_id=parent_id,
                currency=currency,
                is_header=is_header,
                level=level,
                description=description
            )
            
            db.session.add(account)
            db.session.commit()
            
            create_audit_log('create', 'gl_accounts', account.id)
            flash(f'✅ تم إنشاء الحساب {account.full_name} بنجاح', 'success')
            return redirect(url_for('ledger.admin_accounts'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
    
    # الحصول على الحسابات الرئيسية للقائمة المنسدلة
    parent_accounts = GLAccount.query.filter_by(is_header=True).order_by(GLAccount.code).all()
    return render_template('admin/ledger/add_account.html', parent_accounts=parent_accounts)

@ledger_bp.route('/admin-vaults')
@login_required
@permission_required('admin')
def admin_vaults():
    """إدارة الصناديق والمحافظ"""
    vaults = PaymentVault.query.all()
    return render_template('admin/ledger/vaults.html', vaults=vaults)

@ledger_bp.route('/admin-journals')
@login_required
@permission_required('admin')
def admin_journals():
    """إدارة القيود المحاسبية"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    entries = GLJournalEntry.query.order_by(GLJournalEntry.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('admin/ledger/journals.html', entries=entries)

@ledger_bp.route('/admin-reports')
@login_required
@permission_required('admin')
def admin_reports():
    """التقارير المالية المتقدمة"""
    return render_template('admin/ledger/reports.html')

@ledger_bp.route('/admin-trial-balance')
@login_required
@permission_required('admin')
def admin_trial_balance():
    """ميزان المراجعة"""
    date_from = request.args.get('date_from', date.today().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', date.today().strftime('%Y-%m-%d'))
    
    # تحويل التواريخ
    try:
        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        date_from = date_to = date.today()
    
    # حساب أرصدة الحسابات
    accounts = GLAccount.query.filter_by(is_active=True, is_header=False).order_by(GLAccount.code).all()
    trial_balance_data = []
    
    total_debit = total_credit = 0
    
    for account in accounts:
        balance = account.get_balance(date_from, date_to)
        if balance != 0:
            trial_balance_data.append({
                'account': account,
                'debit': balance if balance > 0 else 0,
                'credit': abs(balance) if balance < 0 else 0
            })
            total_debit += balance if balance > 0 else 0
            total_credit += abs(balance) if balance < 0 else 0
    
    return render_template('admin/ledger/trial_balance.html',
                         trial_balance_data=trial_balance_data,
                         total_debit=total_debit,
                         total_credit=total_credit,
                         date_from=date_from,
                         date_to=date_to)

@ledger_bp.route('/admin-balance-sheet')
@login_required
@permission_required('admin')
def admin_balance_sheet():
    """الميزانية العمومية"""
    as_of_date = request.args.get('as_of_date', date.today().strftime('%Y-%m-%d'))
    
    try:
        as_of_date = datetime.strptime(as_of_date, '%Y-%m-%d').date()
    except:
        as_of_date = date.today()
    
    # الأصول
    assets = GLAccount.query.filter_by(type='asset', is_active=True, is_header=False).order_by(GLAccount.code).all()
    assets_total = sum(account.get_balance(as_of_date=as_of_date) for account in assets)
    
    # الخصوم
    liabilities = GLAccount.query.filter_by(type='liability', is_active=True, is_header=False).order_by(GLAccount.code).all()
    liabilities_total = sum(abs(account.get_balance(as_of_date=as_of_date)) for account in liabilities)
    
    # حقوق الملكية
    equity = GLAccount.query.filter_by(type='equity', is_active=True, is_header=False).order_by(GLAccount.code).all()
    equity_total = sum(abs(account.get_balance(as_of_date=as_of_date)) for account in equity)
    
    return render_template('admin/ledger/balance_sheet.html',
                         assets=assets,
                         assets_total=assets_total,
                         liabilities=liabilities,
                         liabilities_total=liabilities_total,
                         equity=equity,
                         equity_total=equity_total,
                         as_of_date=as_of_date)

@ledger_bp.route('/admin-income-statement')
@login_required
@permission_required('admin')
def admin_income_statement():
    """قائمة الدخل"""
    date_from = request.args.get('date_from', (date.today() - timedelta(days=30)).strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', date.today().strftime('%Y-%m-%d'))
    
    try:
        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        date_from = date.today() - timedelta(days=30)
        date_to = date.today()
    
    # الإيرادات
    revenues = GLAccount.query.filter_by(type='revenue', is_active=True, is_header=False).order_by(GLAccount.code).all()
    revenues_total = sum(abs(account.get_balance(date_from, date_to)) for account in revenues)
    
    # المصروفات
    expenses = GLAccount.query.filter_by(type='expense', is_active=True, is_header=False).order_by(GLAccount.code).all()
    expenses_total = sum(account.get_balance(date_from, date_to) for account in expenses)
    
    net_income = revenues_total - expenses_total
    
    return render_template('admin/ledger/income_statement.html',
                         revenues=revenues,
                         revenues_total=revenues_total,
                         expenses=expenses,
                         expenses_total=expenses_total,
                         net_income=net_income,
                         date_from=date_from,
                         date_to=date_to)

@ledger_bp.route('/admin-settings')
@login_required
@permission_required('admin')
def admin_settings():
    """إعدادات النظام المحاسبي"""
    return render_template('admin/ledger/settings.html')

