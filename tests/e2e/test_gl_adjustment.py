"""Assert that a manual stock adjustment actually books a GL entry.

The point of the fix is the journal, not the response: before it, the handler
moved current_stock and wrote the movement row and stopped, so inventory value
drifted from cost silently. A test that only checks the HTTP status would pass
against the old code too.
"""
from decimal import Decimal


def test_stock_adjustment_posts_gl(app, db, users, client, login_as, product,
                                   warehouse):
    from models import GLJournalEntry as GLEntry

    login_as('owner')
    entries_before = GLEntry.query.count()

    r = client.post(f'/products/{product.id}/adjust-stock', data={
        'adjustment_type': 'subtract',
        'quantity': '10',
        'reason': 'stock count',
    })
    assert r.status_code == 200, r.status_code
    assert r.get_json()['success'] is True

    db.session.expire_all()
    entries_after = GLEntry.query.count()
    assert entries_after == entries_before + 1, (
        'the stock moved but no journal entry was booked; inventory value '
        'now disagrees with cost and nothing records why')

    entry = GLEntry.query.order_by(GLEntry.id.desc()).first()
    lines = list(entry.lines)
    assert lines, 'the entry has no lines'

    debits = sum(Decimal(str(line.debit or 0)) for line in lines)
    credits = sum(Decimal(str(line.credit or 0)) for line in lines)
    assert debits == credits, (
        f'the adjustment entry is unbalanced: Dr={debits} Cr={credits}')

    accounts = {line.account.code for line in lines}
    assert '1140' in accounts and '5150' in accounts, (
        f'the adjustment did not use the inventory pair: {accounts}')


def test_stock_adjustment_gain_uses_the_opposite_pair(
        app, db, users, client, login_as, product, warehouse):
    from models import GLJournalEntry as GLEntry

    login_as('owner')
    before = GLEntry.query.count()

    r = client.post(f'/products/{product.id}/adjust-stock', data={
        'adjustment_type': 'add',
        'quantity': '5',
        'reason': 'found stock',
    })
    assert r.status_code == 200, r.status_code

    db.session.expire_all()
    assert GLEntry.query.count() == before + 1

    entry = GLEntry.query.order_by(GLEntry.id.desc()).first()
    inventory = next(l for l in entry.lines if l.account.code == '1140')
    adjustment = next(l for l in entry.lines if l.account.code == '5150')

    assert Decimal(str(inventory.debit or 0)) > 0, (
        'a stock increase must debit inventory')
    assert Decimal(str(adjustment.credit or 0)) > 0, (
        'a stock increase must credit the adjustment expense')