"""A posting on a header account is silently invisible.

gl_service.ensure_core_accounts creates 5000 with is_header=True at depth 0, so
it is a roll-up node. Posting cost of sales there means the trial balance reads
zero at every level that aggregates 5000, and nothing errors: the entry is
accepted and simply never surfaces.

sale_service.FALLBACK_ACCOUNTS is the code used when AccountResolver cannot be
imported, so it has to name a posting leaf rather than the header above it.
"""
from models import GLAccount
from services.gl_service import GLService


def test_5000_is_a_header_and_5100_is_a_posting_leaf(app, db, users):
    GLService.ensure_core_accounts()
    db.session.commit()

    header = GLAccount.query.filter_by(code='5000').first()
    leaf = GLAccount.query.filter_by(code='5100').first()
    adjustment = GLAccount.query.filter_by(code='5150').first()

    assert header is not None, '5000 is missing from the chart'
    assert leaf is not None, '5100 is missing from the chart'
    assert adjustment is not None, '5150 is missing from the chart'

    assert header.is_header is True, (
        'the premise is wrong: 5000 is not a header')
    assert leaf.is_header is False, (
        'the premise is wrong: 5100 is not a leaf')

    assert leaf.parent_id == header.id, (
        '5100 no longer sits under 5000, so the fallback mapping would be '
        'pointing at an unrelated account')


def test_cogs_fallback_names_the_leaf_not_the_header(app, db, users):
    from services.sale_service import FALLBACK_ACCOUNTS

    cogs = FALLBACK_ACCOUNTS['COGS']
    assert cogs != '5000', (
        'COGS falls back to 5000, which is a header; cost of sales would be '
        'posted to a roll-up node and never appear in the trial balance')
    assert cogs == '5100', f'expected the 5100 leaf, got {cogs}'


def test_resolver_and_fallback_agree(app, db, users):
    from services.account_resolution import AccountResolver, AccountRole
    from services.sale_service import FALLBACK_ACCOUNTS

    resolved = AccountResolver.resolve(AccountRole.COGS)
    assert resolved == FALLBACK_ACCOUNTS['COGS'], (
        'the resolver and the fallback disagree, so the ledger books cost of '
        'sales to a different account depending on whether an import failed')