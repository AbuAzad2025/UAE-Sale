from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from extensions import db
from models import GLAccount, GLJournalEntry, GLJournalLine
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
            line_count = int(request.form.get('line_count', 0))
            
            for i in range(line_count):
                account_code = request.form.get(f'line_{i}_account')
                debit = request.form.get(f'line_{i}_debit', 0)
                credit = request.form.get(f'line_{i}_credit', 0)
                line_description = request.form.get(f'line_{i}_description', '')
                
                if account_code:
                    lines.append({
                        'account_code': account_code,
                        'debit': float(debit) if debit else 0,
                        'credit': float(credit) if credit else 0,
                        'description': line_description
                    })
            
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
    
    return render_template('ledger/manual_entry.html', accounts=accounts)


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

