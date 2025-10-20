from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func
from extensions import db
from models import GLAccount, GLJournalEntry, GLJournalLine
from utils.decorators import admin_required, permission_required
from decimal import Decimal

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

