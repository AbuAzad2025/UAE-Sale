"""Support tickets — قناة الدعم لكل مستأجر.

تنشئ كل شركة تذاكر دعم أمام المنصة؛ المالك يرى ويُعالج كل التذاكر عبر
/owner/support-tickets. المؤسسة أو المطور المطلوب منه إضافة مسار جديد
يجب أن يُضيفه إلى utils/route_scope.py (حتمي — test_route_isolation_census).
"""

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash)
from flask_login import login_required, current_user

from extensions import db
from models import SupportTicket
from utils.decorators import get_owned_or_404
from utils.helpers import create_audit_log

support_bp = Blueprint('support', __name__, url_prefix='/support')

PRIORITY_CHOICES = ('low', 'normal', 'high', 'urgent')
CATEGORY_CHOICES = ('bug', 'billing', 'howto', 'feature_request', 'other')
CATEGORY_LABEL = {
    'bug': 'عطل',
    'billing': 'اشتراك ودفع',
    'howto': 'كيف أفعل',
    'feature_request': 'طلب ميزة',
    'other': 'أخرى',
}
PRIORITY_LABEL = {'low': 'منخفضة', 'normal': 'عادية', 'high': 'عالية', 'urgent': 'عاجل'}


@support_bp.route('/tickets')
@login_required
def tickets_list():
    """تذاكري في الشركة الحالية."""
    from models.tenant_scope import get_current_tenant_id
    tenant_id = get_current_tenant_id()

    status = (request.args.get('status') or '').strip()
    category = (request.args.get('category') or '').strip()

    query = SupportTicket.query
    if tenant_id is not None:
        query = query.filter(SupportTicket.tenant_id == tenant_id)

    if status in ('open', 'in_progress', 'resolved', 'closed'):
        query = query.filter(SupportTicket.status == status)
    if category in CATEGORY_CHOICES:
        query = query.filter(SupportTicket.category == category)

    tickets = query.order_by(SupportTicket.created_at.desc()).all()
    stats = {
        'open': sum(1 for t in tickets if t.status == 'open'),
        'in_progress': sum(1 for t in tickets if t.status == 'in_progress'),
        'resolved': sum(1 for t in tickets if t.status == 'resolved'),
        'closed': sum(1 for t in tickets if t.status == 'closed'),
    }
    return render_template('support/tickets.html', tickets=tickets, stats=stats,
                           status_filter=status, category_filter=category,
                           category_label=CATEGORY_LABEL, priority_label=PRIORITY_LABEL)


@support_bp.route('/tickets/new', methods=['GET', 'POST'])
@login_required
def ticket_new():
    if request.method == 'POST':
        from models.tenant_scope import get_current_tenant_id
        tenant_id = get_current_tenant_id()
        subject = (request.form.get('subject') or '').strip()
        description = (request.form.get('description') or '').strip()
        priority = (request.form.get('priority') or 'normal').strip()
        category = (request.form.get('category') or 'other').strip()
        if not subject or not description:
            flash('الموضوع والوصف مطلوبان', 'danger')
            return redirect(url_for('support.ticket_new'))
        if priority not in PRIORITY_CHOICES:
            priority = 'normal'
        if category not in CATEGORY_CHOICES:
            category = 'other'
        row = SupportTicket(
            tenant_id=tenant_id,
            author_user_id=current_user.id,
            subject=subject,
            description=description,
            priority=priority,
            category=category,
        )
        db.session.add(row)
        db.session.commit()
        create_audit_log('create_support_ticket', 'support_tickets', row.id,
                         changes={'subject': subject, 'priority': priority,
                                  'category': category})
        flash('✅ تم فتح التذكرة — سنرد عليك ضمن SLA الموضح', 'success')
        return redirect(url_for('support.ticket_view', id=row.id))
    return render_template('support/new.html', category_label=CATEGORY_LABEL,
                           priority_label=PRIORITY_LABEL)


@support_bp.route('/tickets/<int:id>')
@login_required
def ticket_view(id):
    ticket = get_owned_or_404(SupportTicket, id)
    return render_template('support/view.html', ticket=ticket,
                           category_label=CATEGORY_LABEL, priority_label=PRIORITY_LABEL)
