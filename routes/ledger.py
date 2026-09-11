from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from extensions import db
from models import GLAccount, GLJournalEntry, GLJournalLine, Cheque, PaymentVault
from services.gl_service import GLService
from services.cash_flow_service import CashFlowService
from services.aging_analysis_service import AgingAnalysisService
from utils.decorators import admin_required, permission_required, get_owned_or_404
from utils.helpers import create_audit_log
from decimal import Decimal
from datetime import datetime, date, timedelta

ledger_bp = Blueprint('ledger', __name__, url_prefix='/ledger')


@ledger_bp.route('/')
@login_required
@permission_required('view_ledger')
def index():
    accounts = GLAccount.query.filter_by(is_active=True).order_by(GLAccount.code).all()
    # Dashboard stats (merged from the admin twin — single ledger home).
    total_accounts = GLAccount.query.count()
    total_entries = GLJournalEntry.query.count()
    posted_entries = GLJournalEntry.query.filter_by(is_posted=True).count()
    cash_accounts = GLAccount.query.filter(GLAccount.code.like('11%')).all()
    total_cash = sum((a.get_balance() for a in cash_accounts), Decimal('0'))
    recent_entries = GLJournalEntry.query.order_by(
        GLJournalEntry.created_at.desc()).limit(10).all()
    stats = {
        'total_accounts': total_accounts,
        'active_accounts': len(accounts),
        'total_entries': total_entries,
        'posted_entries': posted_entries,
        'total_cash': float(total_cash),
    }
    return render_template('ledger/index.html', accounts=accounts,
                           stats=stats, recent_entries=recent_entries)


@ledger_bp.route('/account/<int:id>')
@login_required
@permission_required('view_ledger')
def account_ledger(id):
    account = db.get_or_404(GLAccount, id)

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
    # Optional date window (merged from the admin twin): absent = all-time.
    date_from = request.args.get('date_from', type=str) or None
    date_to = request.args.get('date_to', type=str) or None
    try:
        df = datetime.strptime(date_from, '%Y-%m-%d').date() if date_from else None
        dt = datetime.strptime(date_to, '%Y-%m-%d').date() if date_to else None
    except (ValueError, TypeError):
        flash('⚠️ صيغة التاريخ غير صالحة — تم تجاهل فلتر التاريخ.', 'warning')
        df = dt = None
        date_from = date_to = None

    # Single GROUP BY query: per-account debit/credit sums in one round trip.
    sums_q = db.session.query(
        GLJournalLine.account_id.label('account_id'),
        func.sum(GLJournalLine.debit).label('debit_sum'),
        func.sum(GLJournalLine.credit).label('credit_sum'),
    )
    if df or dt:
        sums_q = sums_q.join(GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id)
        if df:
            sums_q = sums_q.filter(func.date(GLJournalEntry.entry_date) >= df)
        if dt:
            sums_q = sums_q.filter(func.date(GLJournalEntry.entry_date) <= dt)
    sums_q = sums_q.group_by(GLJournalLine.account_id)
    sums_by_account = {
        row.account_id: ((row.debit_sum or Decimal('0')), (row.credit_sum or Decimal('0')))
        for row in sums_q.all()
    }

    accounts = GLAccount.query.filter_by(is_active=True).order_by(GLAccount.code).all()

    trial_data = []
    total_debit = Decimal('0')
    total_credit = Decimal('0')
    total_debit_balance = Decimal('0')
    total_credit_balance = Decimal('0')

    for account in accounts:
        debit_sum, credit_sum = sums_by_account.get(account.id, (Decimal('0'), Decimal('0')))

        balance = debit_sum - credit_sum

        if balance != 0 or debit_sum != 0 or credit_sum != 0:
            debit_bal = balance if balance > 0 else Decimal('0')
            credit_bal = abs(balance) if balance < 0 else Decimal('0')

            trial_data.append({
                'account': account,
                'debit': float(debit_sum),
                'credit': float(credit_sum),
                'balance': float(balance),
                'debit_balance': float(debit_bal),
                'credit_balance': float(credit_bal)
            })

            total_debit += debit_sum
            total_credit += credit_sum
            total_debit_balance += debit_bal
            total_credit_balance += credit_bal

    is_balanced = (total_debit == total_credit)
    is_net_balanced = (total_debit_balance == total_credit_balance)

    return render_template('ledger/trial_balance.html',
                           trial_data=trial_data,
                           total_debit=float(total_debit),
                           total_credit=float(total_credit),
                           total_debit_balance=float(total_debit_balance),
                           total_credit_balance=float(total_credit_balance),
                           is_balanced=is_balanced,
                           is_net_balanced=is_net_balanced,
                           date_from=date_from or '',
                           date_to=date_to or '')


@ledger_bp.route('/journal-entries')
@login_required
@permission_required('view_ledger')
def journal_entries():
    page = request.args.get('page', 1, type=int)
    status = (request.args.get('status') or '').strip()
    entry_type = (request.args.get('entry_type') or '').strip()
    q = (request.args.get('q') or '').strip()

    query = GLJournalEntry.query
    if status == 'posted':
        query = query.filter_by(is_posted=True, is_reversed=False)
    elif status == 'draft':
        query = query.filter_by(is_posted=False)
    elif status == 'reversed':
        query = query.filter_by(is_reversed=True)
    if entry_type in ('manual', 'auto', 'reversing', 'closing'):
        query = query.filter_by(entry_type=entry_type)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            GLJournalEntry.entry_number.ilike(like),
            GLJournalEntry.description.ilike(like),
        ))

    pagination = query.order_by(GLJournalEntry.entry_date.desc()).paginate(
        page=page,
        per_page=50,
        error_out=False
    )

    return render_template('ledger/journal_entries.html',
                           entries=pagination.items,
                           pagination=pagination,
                           status=status,
                           entry_type=entry_type,
                           q=q)


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
        query_credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=acc.id).join(GLJournalEntry)
        query_debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=acc.id).join(GLJournalEntry)

        if date_from:
            query_credit = query_credit.filter(func.date(GLJournalEntry.entry_date) >= date_from)
            query_debit = query_debit.filter(func.date(GLJournalEntry.entry_date) >= date_from)

        if date_to:
            query_credit = query_credit.filter(func.date(GLJournalEntry.entry_date) <= date_to)
            query_debit = query_debit.filter(func.date(GLJournalEntry.entry_date) <= date_to)

        credit = query_credit.scalar() or Decimal('0')
        debit = query_debit.scalar() or Decimal('0')
        balance = credit - debit

        if balance != 0:
            revenues[acc.name] = float(balance)
            total_revenue += balance

    expenses = {}
    total_expense = Decimal('0')

    for acc in expense_accounts:
        query_debit = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=acc.id).join(GLJournalEntry)
        query_credit = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=acc.id).join(GLJournalEntry)

        if date_from:
            query_debit = query_debit.filter(func.date(GLJournalEntry.entry_date) >= date_from)
            query_credit = query_credit.filter(func.date(GLJournalEntry.entry_date) >= date_from)

        if date_to:
            query_debit = query_debit.filter(func.date(GLJournalEntry.entry_date) <= date_to)
            query_credit = query_credit.filter(func.date(GLJournalEntry.entry_date) <= date_to)

        debit = query_debit.scalar() or Decimal('0')
        credit = query_credit.scalar() or Decimal('0')
        balance = debit - credit

        if balance != 0:
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
    # Optional as-of date (merged from the admin twin): absent = all-time.
    as_of_raw = request.args.get('as_of_date', type=str) or None
    try:
        as_of_date = datetime.strptime(as_of_raw, '%Y-%m-%d').date() if as_of_raw else None
    except (ValueError, TypeError):
        from flask import current_app
        current_app.logger.warning(f'Ledger balance-sheet: ignoring unparsable as_of_date={as_of_raw!r}')
        flash('⚠️ صيغة التاريخ غير صالحة — تم تجاهل فلتر التاريخ.', 'warning')
        as_of_date = None
        as_of_raw = None

    def _sums(account_id):
        dq = db.session.query(func.sum(GLJournalLine.debit)).filter_by(account_id=account_id)
        cq = db.session.query(func.sum(GLJournalLine.credit)).filter_by(account_id=account_id)
        if as_of_date is not None:
            dq = dq.join(GLJournalEntry).filter(func.date(GLJournalEntry.entry_date) <= as_of_date)
            cq = cq.join(GLJournalEntry).filter(func.date(GLJournalEntry.entry_date) <= as_of_date)
        return (dq.scalar() or Decimal('0')), (cq.scalar() or Decimal('0'))

    assets = {}
    liabilities = {}
    equity = {}

    asset_accounts = GLAccount.query.filter(GLAccount.code.like('1%')).all()
    liability_accounts = GLAccount.query.filter(GLAccount.code.like('2%')).all()
    equity_accounts = GLAccount.query.filter(GLAccount.code.like('3%')).all()

    total_assets = Decimal('0')
    for acc in asset_accounts:
        debit, credit = _sums(acc.id)
        balance = debit - credit

        if balance != 0:
            assets[acc.name] = float(balance)
            total_assets += balance

    total_liabilities = Decimal('0')
    for acc in liability_accounts:
        debit, credit = _sums(acc.id)
        balance = credit - debit

        if balance != 0:
            liabilities[acc.name] = float(balance)
            total_liabilities += balance

    total_equity = Decimal('0')
    for acc in equity_accounts:
        debit, credit = _sums(acc.id)
        balance = credit - debit

        if balance != 0:
            equity[acc.name] = float(balance)
            total_equity += balance

    # Calculate Net Profit (Revenue - Expenses) for Equity Section
    revenue_accounts = GLAccount.query.filter(GLAccount.code.like('4%')).all()
    expense_accounts = GLAccount.query.filter(GLAccount.code.like('5%')).all()
    expense_accounts += GLAccount.query.filter(GLAccount.code.like('6%')).all()

    total_revenue_period = Decimal('0')
    for acc in revenue_accounts:
        debit, credit = _sums(acc.id)
        total_revenue_period += (credit - debit)

    total_expense_period = Decimal('0')
    for acc in expense_accounts:
        debit, credit = _sums(acc.id)
        total_expense_period += (debit - credit)

    net_profit_period = total_revenue_period - total_expense_period

    if net_profit_period != 0:
        equity['الأرباح المبقاة (صافي الربح التراكمي)'] = float(net_profit_period)
        total_equity += net_profit_period

    return render_template('ledger/balance_sheet.html',
                           assets=assets,
                           liabilities=liabilities,
                           equity=equity,
                           total_assets=float(total_assets),
                           total_liabilities=float(total_liabilities),
                           total_equity=float(total_equity),
                           as_of_date=as_of_raw or '')


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
def manual_entry():  # noqa: C901
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
                    debit_value = float(str(debit).strip()) if debit and str(debit).strip() else 0
                    credit_value = float(str(credit).strip()) if credit and str(credit).strip() else 0
                except (ValueError, AttributeError, TypeError):
                    raise ValueError(f'❌ قيمة غير صالحة في السطر {i + 1}: تحقق من المدين/الدائن.')

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
            flash(f'❌ خطأ: {str(e)}\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')

    # الحصول على الحسابات النشطة (غير رئيسية)
    accounts = GLAccount.query.filter_by(is_active=True, is_header=False).order_by(GLAccount.code).all()

    return render_template('ledger/manual_entry.html', accounts=accounts, today=date.today())


@ledger_bp.route('/entry/<int:id>')
@login_required
@permission_required('view_ledger')
def view_entry(id):
    """عرض تفاصيل القيد"""
    entry = get_owned_or_404(GLJournalEntry, id)
    lines = entry.lines.all()

    return render_template('ledger/view_entry.html', entry=entry, lines=lines)


@ledger_bp.route('/entry/<int:id>/reverse', methods=['POST'])
@login_required
@permission_required('manage_ledger')
def reverse_entry(id):
    """عكس القيد (عبر مدير القيود المتقدم: موثق ومحمي من العكس المزدوج)"""
    from services.advanced_journal_manager import AdvancedJournalEntryManager
    entry = get_owned_or_404(GLJournalEntry, id)
    try:
        reason = request.form.get('description') or request.form.get('reason') or 'عكس القيد'
        reversed_entry = AdvancedJournalEntryManager.reverse_entry_advanced(
            entry.id, current_user.id, reason)

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


@ledger_bp.route('/entry/<int:id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_entry(id):
    """الموافقة على قيد مسودة وترحيله"""
    from services.advanced_journal_manager import AdvancedJournalEntryManager
    try:
        approval_notes = request.form.get('approval_notes', 'موافقة على القيد')

        AdvancedJournalEntryManager.approve_entry(
            entry_id=id,
            approved_by=current_user.id,
            approval_notes=approval_notes
        )

        flash('✅ تم الموافقة على القيد وترحيله بنجاح', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')

    return redirect(url_for('ledger.view_entry', id=id))


@ledger_bp.route('/entry/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_entry(id):
    """حذف قيد مسودة (المرحّل محمي: مرفوض)"""
    from services.advanced_journal_manager import AdvancedJournalEntryManager
    try:
        reason = request.form.get('reason', 'حذف القيد')

        AdvancedJournalEntryManager.delete_entry(
            entry_id=id,
            deleted_by=current_user.id,
            reason=reason
        )

        flash('✅ تم حذف القيد بنجاح', 'success')
        return redirect(url_for('ledger.journal_entries'))

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
        GLAccount.is_active.is_(True),
        GLAccount.is_header.is_(False),
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
@login_required
@permission_required('view_ledger')
def api_calculate_journal_balance():
    """API لحساب توازن القيد اليدوي - Backend Calculation"""
    # Dual-check: read-only calculation serves ledger viewers and editors alike
    if not (current_user.has_permission('view_ledger') or current_user.has_permission('manage_ledger')):
        abort(403)
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
        flash(f'❌ فشل إنشاء قائمة التدفقات: {str(e)}\n💡 تحقق من الفترة المحددة وحاول مرة أخرى.', 'danger')
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
        flash(f'❌ فشل إنشاء تحليل الأعمار: {str(e)}\n💡 تحقق من البيانات وحاول مرة أخرى.', 'danger')
        return redirect(url_for('ledger.index'))


# ==================== إدارة الحسابات والخزائن والتقارير ====================
# Canonical homes (merged from the retired admin_ledger blueprint):
# accounts CRUD, vaults, reports hub, settings, account JSON APIs.


@ledger_bp.route('/accounts')
@login_required
@admin_required
def accounts():
    """إدارة الحسابات المحاسبية"""
    accounts = GLAccount.query.order_by(GLAccount.code).all()
    return render_template('ledger/accounts.html', accounts=accounts)


@ledger_bp.route('/accounts/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_account():
    """إضافة حساب محاسبي جديد"""
    parent_accounts = GLAccount.query.filter_by(is_header=True).order_by(GLAccount.code).all()
    default_form = {'is_active': 'on'}

    if request.method == 'POST':
        try:
            code = (request.form.get('code') or '').strip()
            name = (request.form.get('name') or '').strip()
            name_ar = (request.form.get('name_ar') or '').strip()
            account_type = (request.form.get('type') or '').strip()
            parent_id_raw = (request.form.get('parent_id') or '').strip()
            parent_id = int(parent_id_raw) if parent_id_raw else None
            currency = request.form.get('currency', 'AED')
            is_header = 'on' in request.form.getlist('is_header')
            is_active = 'on' in request.form.getlist('is_active')
            description = request.form.get('description')

            if not account_type:
                flash('⚠️ يرجى اختيار نوع الحساب.', 'warning')
                form_values = request.form.to_dict()
                form_values['is_header'] = 'on' if is_header else 'off'
                form_values['is_active'] = 'on' if is_active else 'off'
                return render_template('ledger/add_account.html',
                                       parent_accounts=parent_accounts,
                                       form_data=form_values)

            # التحقق من عدم تكرار الكود
            existing = GLAccount.query.filter_by(code=code).first()
            if existing:
                flash('❌ كود الحساب موجود مسبقاً', 'danger')
                form_values = request.form.to_dict()
                form_values['is_header'] = 'on' if is_header else 'off'
                form_values['is_active'] = 'on' if is_active else 'off'
                return render_template('ledger/add_account.html',
                                       parent_accounts=parent_accounts,
                                       form_data=form_values)

            # حساب المستوى
            level = 0
            if parent_id:
                parent = db.session.get(GLAccount, parent_id)
                level = parent.level + 1 if parent else 0

            account = GLAccount(
                code=code,
                name=name,
                name_ar=name_ar,
                type=account_type,
                parent_id=parent_id,
                currency=currency,
                is_header=is_header,
                is_active=is_active,
                level=level,
                description=description
            )

            db.session.add(account)
            db.session.commit()

            create_audit_log('create', 'gl_accounts', account.id)
            flash(f'✅ تم إنشاء الحساب {account.full_name} بنجاح', 'success')
            return redirect(url_for('ledger.accounts'))

        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
            form_values = request.form.to_dict()
            form_values['is_header'] = 'on' if 'on' in request.form.getlist('is_header') else 'off'
            form_values['is_active'] = 'on' if 'on' in request.form.getlist('is_active') else 'off'
            return render_template('ledger/add_account.html',
                                   parent_accounts=parent_accounts,
                                   form_data=form_values)

    return render_template('ledger/add_account.html',
                           parent_accounts=parent_accounts,
                           form_data=default_form)


@ledger_bp.route('/accounts/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_account(id):
    """تعديل حساب محاسبي"""
    account = db.get_or_404(GLAccount, id)

    if request.method == 'POST':
        try:
            account.code = request.form.get('code')
            account.name = request.form.get('name')
            account.name_ar = request.form.get('name_ar')
            account.type = request.form.get('type')
            account.parent_id = request.form.get('parent_id') or None
            account.currency = request.form.get('currency', 'AED')
            account.is_header = bool(request.form.get('is_header'))
            account.description = request.form.get('description')
            account.is_active = bool(request.form.get('is_active'))

            # حساب المستوى
            if account.parent_id:
                parent = db.session.get(GLAccount, account.parent_id)
                account.level = parent.level + 1 if parent else 0
            else:
                account.level = 0

            db.session.commit()

            create_audit_log('update', 'gl_accounts', account.id)
            flash(f'✅ تم تحديث الحساب {account.full_name} بنجاح', 'success')
            return redirect(url_for('ledger.accounts'))

        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    parent_accounts = GLAccount.query.filter_by(is_header=True).order_by(GLAccount.code).all()
    return render_template('ledger/edit_account.html', account=account, parent_accounts=parent_accounts)


@ledger_bp.route('/accounts/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_account(id):
    """حذف حساب محاسبي"""
    account = db.get_or_404(GLAccount, id)

    try:
        # التحقق من وجود قيود مرتبطة
        has_entries = GLJournalLine.query.filter_by(account_id=id).first()
        if has_entries:
            flash('❌ لا يمكن حذف الحساب لوجود قيود مرتبطة به', 'danger')
            return redirect(url_for('ledger.accounts'))

        # التحقق من وجود حسابات فرعية
        has_children = GLAccount.query.filter_by(parent_id=id).first()
        if has_children:
            flash('❌ لا يمكن حذف الحساب لوجود حسابات فرعية مرتبطة به', 'danger')
            return redirect(url_for('ledger.accounts'))

        db.session.delete(account)
        db.session.commit()

        create_audit_log('delete', 'gl_accounts', id)
        flash(f'✅ تم حذف الحساب {account.full_name} بنجاح', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')

    return redirect(url_for('ledger.accounts'))


@ledger_bp.route('/vaults')
@login_required
@admin_required
def vaults():
    """إدارة الصناديق والمحافظ"""
    vaults = PaymentVault.query.all()
    return render_template('ledger/vaults.html', vaults=vaults)


@ledger_bp.route('/reports')
@login_required
@permission_required('view_ledger')
def reports():
    """مركز التقارير المالية"""
    return render_template('ledger/reports.html')


@ledger_bp.route('/settings')
@login_required
@admin_required
def settings():
    """إعدادات النظام المحاسبي"""
    return render_template('ledger/settings.html')


@ledger_bp.route('/api/account-balance/<int:account_id>')
@login_required
@admin_required
def api_account_balance(account_id):
    """API للحصول على رصيد حساب"""
    account = db.get_or_404(GLAccount, account_id)
    balance = account.get_balance()

    return jsonify({
        'account_code': account.code,
        'account_name': account.full_name,
        'balance': float(balance),
        'balance_formatted': f"{balance:,.2f}"
    })


@ledger_bp.route('/api/account-statement/<int:account_id>')
@login_required
@admin_required
def api_account_statement(account_id):
    """API لكشف حساب"""
    account = db.get_or_404(GLAccount, account_id)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    statement = GLService.get_account_statement(account_id, date_from, date_to)

    # get_account_statement includes the ORM object itself for templates;
    # strip it before serializing to JSON.
    statement.pop('account', None)

    return jsonify({
        'account': {
            'code': account.code,
            'name': account.full_name
        },
        'statement': statement
    })
