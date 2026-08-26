"""Double-entry & journal integrity sweep (القيود والترحيل).

Property-style harness driving REAL flows only:
  * SaleService.create_sale — plain, partial, full, overpaid, cheque,
    multi-line (discount/tax/shipping) and foreign-currency paths
  * SaleService.create_payment_for_sale
  * SaleService.cancel_sale — must post REVERSING entries, never delete
  * AdvancedJournalEntryManager — create / update draft / approve /
    reverse / delete

For EVERY GLJournalEntry in the ledger it asserts:
  1. abs(sum(debit) - sum(credit)) <= 0.0001
  2. at least 2 lines
  3. no line carries both debit > 0 and credit > 0
  4. entry.total_debit / total_credit equal the line sums
  5. immutable fields of already-posted entries never change after
     subsequent operations (is_reversed / reversed_entry_id / updated_at are
     the ONLY fields a reversal may touch on the original)

Deterministic & offline: every FX conversion passes an explicit user rate,
so CurrencyService never reaches the network.
"""

from decimal import Decimal

import pytest

from models import GLJournalEntry, Product, Warehouse
from services.advanced_journal_manager import AdvancedJournalEntryManager
from services.sale_service import SaleService

TOLERANCE = Decimal('0.0001')


@pytest.fixture
def warehouse(db):
    wh = Warehouse(name='Integrity WH', name_ar='مستودع الفحص',
                   code='WH-INT-01', is_active=True, is_main=True)
    db.session.add(wh)
    db.session.commit()
    return wh


@pytest.fixture
def second_product(db, test_category):
    product = Product(
        name='Integrity Oil Filter', name_ar='فلتر زيت',
        sku='SKU-INT-002', category_id=test_category.id,
        cost_price=Decimal('12.500'), regular_price=Decimal('40.000'),
        current_stock=Decimal('80'), min_stock_alert=Decimal('5'),
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


def _money(value):
    """Normalize Numeric() round-trips (SQLite re-quantizes after expiry)."""
    return f'{Decimal(str(value)):.3f}'


def _fx(value):
    return f'{Decimal(str(value)):.6f}'


def _naive(value):
    """SQLite returns naive datetimes after expiry; strip tz for stability."""
    if value is not None and getattr(value, 'tzinfo', None) is not None:
        return str(value.replace(tzinfo=None))
    return str(value)


def _snapshot_entry(entry):
    """Immutable business/financial fingerprint of a journal entry."""
    return (
        entry.id,
        entry.entry_number,
        entry.description,
        entry.reference_type,
        entry.reference_id,
        entry.currency,
        _fx(entry.exchange_rate),
        _money(entry.total_debit),
        _money(entry.total_credit),
        _naive(entry.created_at),
        tuple(sorted(
            (ln.account_id, _money(ln.debit), _money(ln.credit))
            for ln in entry.lines
        )),
    )


def _snapshot_all(reference_type=None, reference_id=None):
    query = GLJournalEntry.query
    if reference_type:
        query = query.filter_by(reference_type=reference_type, reference_id=reference_id)
    return {e.id: _snapshot_entry(e) for e in query.all()}


def assert_snapshots_unchanged(before, label):
    after = {e.id: _snapshot_entry(e) for e in GLJournalEntry.query.all()}
    for entry_id, old in before.items():
        assert entry_id in after, f'{label}: entry #{entry_id} disappeared (deleted?)'
        assert after[entry_id] == old, f'{label}: immutable entry #{entry_id} mutated'


def assert_ledger_invariants(min_entries=1):
    """Core double-entry properties over the WHOLE ledger."""
    entries = GLJournalEntry.query.all()
    assert len(entries) >= min_entries
    for entry in entries:
        lines = entry.lines.all()
        assert len(lines) >= 2, f'{entry.entry_number}: needs >= 2 lines'
        sum_dr = sum((Decimal(str(ln.debit or 0)) for ln in lines), Decimal('0'))
        sum_cr = sum((Decimal(str(ln.credit or 0)) for ln in lines), Decimal('0'))
        assert abs(sum_dr - sum_cr) <= TOLERANCE, (
            f'{entry.entry_number}: unbalanced dr={sum_dr} cr={sum_cr}'
        )
        for ln in lines:
            debit = Decimal(str(ln.debit or 0))
            credit = Decimal(str(ln.credit or 0))
            assert not (debit > 0 and credit > 0), (
                f'{entry.entry_number}: line #{ln.id} has both sides '
                f'(dr={debit}, cr={credit})'
            )
        entry_dr = Decimal(str(entry.total_debit or 0))
        entry_cr = Decimal(str(entry.total_credit or 0))
        assert abs(entry_dr - sum_dr) <= TOLERANCE, (
            f'{entry.entry_number}: header total_debit {entry_dr} != line sum {sum_dr}'
        )
        assert abs(entry_cr - sum_cr) <= TOLERANCE, (
            f'{entry.entry_number}: header total_credit {entry_cr} != line sum {sum_cr}'
        )
    return entries


def _build_sale(customer, seller, product, second_product, warehouse, idx, variant):
    lines_data = [
        {'product': product, 'quantity': Decimal(str(1 + idx % 3)),
         'unit_price': Decimal('50.000'), 'discount_percent': Decimal('10')},
    ]
    kwargs = dict(
        warehouse_id=warehouse.id,
        currency='ILS',
        user_exchange_rate=Decimal('1'),
    )

    if variant == 'plain':
        lines_data = [{'product': product, 'quantity': Decimal('2'),
                       'unit_price': Decimal('50.000')}]
    elif variant == 'partial_cash':
        kwargs['payment_data'] = {
            'amount': Decimal('25.000'), 'payment_method': 'cash',
            'currency': 'ILS', 'exchange_rate': 1.0,
        }
    elif variant == 'full_cash':
        kwargs['payment_data'] = {
            'amount': Decimal('90.000'), 'payment_method': 'cash',
            'currency': 'ILS', 'exchange_rate': 1.0,
        }
    elif variant == 'cheque':
        kwargs['payment_data'] = {
            'amount': Decimal('45.000'), 'payment_method': 'cheque',
            'currency': 'ILS', 'exchange_rate': 1.0,
            'cheque_number': f'CHQ-INT-{idx:04d}',
            'cheque_date': '2026-09-30',
            'bank_name': 'Integrity Bank',
        }
    elif variant == 'overpaid':
        kwargs['discount_amount'] = Decimal('5')
        kwargs['shipping_cost'] = Decimal('7')
        kwargs['tax_rate'] = Decimal('5')
        kwargs['payment_data'] = {
            'amount': Decimal('200.000'), 'payment_method': 'card',
            'currency': 'ILS', 'exchange_rate': 1.0,
        }
    elif variant == 'multi_line_tax_shipping':
        lines_data.append({'product': second_product, 'quantity': Decimal('3'),
                           'unit_price': Decimal('40.000'),
                           'discount_percent': Decimal('25')})
        kwargs['discount_amount'] = Decimal('10')
        kwargs['shipping_cost'] = Decimal('15')
        kwargs['tax_rate'] = Decimal('10')
    elif variant == 'foreign_currency':
        kwargs['currency'] = 'AED'
        kwargs['user_exchange_rate'] = Decimal('1.750')
        kwargs['payment_data'] = {
            'amount': Decimal('20.000'), 'payment_method': 'bank_transfer',
            'currency': 'AED', 'exchange_rate': 1.75,
        }
    else:
        raise AssertionError(f'unknown variant {variant}')

    return SaleService.create_sale(
        customer=customer, seller=seller, lines_data=lines_data, **kwargs
    )


VARIANTS = [
    'plain', 'partial_cash', 'full_cash', 'cheque',
    'overpaid', 'multi_line_tax_shipping', 'foreign_currency',
]


class TestSaleFlowLedgerInvariants:
    def test_every_sale_variant_keeps_ledger_balanced(
            self, db, owner_user, test_customer, test_product, second_product,
            warehouse):
        posted_fingerprint = {}
        for idx, variant in enumerate(VARIANTS):
            sale = _build_sale(test_customer, owner_user, test_product,
                               second_product, warehouse, idx, variant)
            assert sale.id is not None

            revenue = GLJournalEntry.query.filter_by(
                reference_type='Sale', reference_id=sale.id,
                description=f'Sale {sale.sale_number}').first()
            assert revenue is not None, f'{variant}: revenue entry missing'
            cogs = GLJournalEntry.query.filter_by(
                reference_type='Sale', reference_id=sale.id)\
                .filter(GLJournalEntry.description.like('COGS%')).first()
            assert cogs is not None, f'{variant}: COGS entry missing'

            # COGS must stay in BASE terms: never scaled by the FX rate.
            expected_cogs = sum(
                (Decimal(str(ln.cost_price)) * Decimal(str(ln.quantity))
                 for ln in sale.lines), Decimal('0')
            ).quantize(Decimal('0.001'))
            cogs_debit = sum(
                (Decimal(str(ln.debit or 0)) for ln in cogs.lines), Decimal('0')
            )
            assert cogs_debit == expected_cogs, (
                f'{variant}: COGS {cogs_debit} != base cost {expected_cogs} '
                '(FX mixing?)'
            )

            posted_fingerprint.update(_snapshot_all())
            assert_ledger_invariants()

        # All previously posted entries remain byte-identical afterwards.
        assert_snapshots_unchanged(posted_fingerprint, 'after all variants')

    def test_foreign_currency_entry_records_fx_metadata(
            self, db, owner_user, test_customer, test_product, warehouse):
        sale = _build_sale(test_customer, owner_user, test_product,
                           test_product, warehouse, 9, 'foreign_currency')
        entry = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id,
            description=f'Sale {sale.sale_number}').first()
        assert entry.currency == 'AED'
        assert Decimal(str(entry.exchange_rate)) == Decimal('1.75')
        assert_ledger_invariants()


class TestCancellationReversalPath:
    def test_cancel_posts_reversing_entries_and_originals_survive(
            self, db, owner_user, test_customer, test_product, warehouse):
        sale = SaleService.create_sale(
            customer=test_customer, seller=owner_user,
            lines_data=[{'product': test_product, 'quantity': Decimal('2'),
                         'unit_price': Decimal('60.000')}],
            warehouse_id=warehouse.id, currency='ILS',
            user_exchange_rate=Decimal('1'),
        )
        originals = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id, is_posted=True).all()
        assert len(originals) >= 2
        before = {o.id: _snapshot_entry(o) for o in originals}
        original_ids = set(before)

        SaleService.cancel_sale(sale)
        db.session.expire_all()

        # Originals still exist and their immutable fields did NOT move.
        after = {e.id: _snapshot_entry(e) for e in GLJournalEntry.query.all()}
        for entry_id, old in before.items():
            assert entry_id in after, 'original entry was deleted on cancel'
            assert after[entry_id] == old, 'original entry mutated on cancel'

        for original in originals:
            reloaded = db.session.get(GLJournalEntry, original.id)
            assert reloaded.is_reversed is True

        # One reversing entry per original, linked back to it.
        reversals = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id,
            entry_type='reversing').all()
        assert len(reversals) == len(originals)
        linked_ids = {r.reversed_entry_id for r in reversals}
        assert linked_ids == original_ids

        for reversal in reversals:
            source = db.session.get(GLJournalEntry, reversal.reversed_entry_id)
            assert reversal.id not in original_ids
            src_lines = sorted(source.lines.all(), key=lambda ln: ln.account_id)
            rev_lines = sorted(reversal.lines.all(), key=lambda ln: ln.account_id)
            assert len(src_lines) == len(rev_lines)
            for src, rev in zip(src_lines, rev_lines):
                assert rev.account_id == src.account_id
                assert rev.debit == src.credit and rev.credit == src.debit
            # Original + reversal cancel out exactly, per account.
            net_per_account = {}
            for ln in source.lines.all() + reversal.lines.all():
                net_per_account.setdefault(ln.account_id, Decimal('0'))
                net_per_account[ln.account_id] += (
                    Decimal(str(ln.debit or 0)) - Decimal(str(ln.credit or 0))
                )
            assert all(v == 0 for v in net_per_account.values()), (
                'original + reversal does not net to zero'
            )

        assert_ledger_invariants()

    def test_cancel_twice_rejected(self, db, owner_user, test_customer,
                                   test_product, warehouse):
        sale = SaleService.create_sale(
            customer=test_customer, seller=owner_user,
            lines_data=[{'product': test_product, 'quantity': Decimal('1'),
                         'unit_price': Decimal('30.000')}],
            warehouse_id=warehouse.id, currency='ILS',
            user_exchange_rate=Decimal('1'),
        )
        SaleService.cancel_sale(sale)
        with pytest.raises(ValueError, match='ملغاة'):
            SaleService.cancel_sale(sale)


class TestJournalManagerIntegrity:
    BALANCED = [
        {'account_code': '1110', 'debit': Decimal('120'), 'credit': Decimal('0')},
        {'account_code': '4100', 'debit': Decimal('0'), 'credit': Decimal('120')},
    ]

    def _draft(self, db, gl_accounts, owner_user):
        entry = AdvancedJournalEntryManager.create_entry_with_validation(
            description=f'draft {owner_user.id}', lines=self.BALANCED,
            created_by=owner_user.id)
        entry.is_posted = False
        db.session.commit()
        return entry

    @pytest.fixture
    def gl_accounts(self, db):
        from services.gl_service import GLService
        GLService.ensure_core_accounts()

    def test_manual_creation_satisfies_invariants(self, db, gl_accounts, owner_user):
        AdvancedJournalEntryManager.create_entry_with_validation(
            description='قيد فحص', lines=self.BALANCED, created_by=owner_user.id)
        assert_ledger_invariants()

    def test_unbalanced_rejected(self, db, gl_accounts, owner_user):
        with pytest.raises(ValueError, match='متوازن|balanced'):
            AdvancedJournalEntryManager.create_entry_with_validation(
                description='غير متوازن',
                lines=[
                    {'account_code': '1110', 'debit': Decimal('100'), 'credit': Decimal('0')},
                    {'account_code': '4100', 'debit': Decimal('0'), 'credit': Decimal('98')},
                ],
                created_by=owner_user.id)

    def test_header_account_rejected(self, db, gl_accounts, owner_user):
        with pytest.raises(ValueError, match='الرئيسي'):
            AdvancedJournalEntryManager.create_entry_with_validation(
                description='على رئيسي',
                lines=[
                    {'account_code': '1000', 'debit': Decimal('10'), 'credit': Decimal('0')},
                    {'account_code': '1110', 'debit': Decimal('0'), 'credit': Decimal('10')},
                ],
                created_by=owner_user.id)

    def test_posted_entry_is_immutable_to_updates(self, db, gl_accounts, owner_user):
        entry = AdvancedJournalEntryManager.create_entry_with_validation(
            description='مرحل', lines=self.BALANCED, created_by=owner_user.id)
        fingerprint = _snapshot_entry(entry)
        with pytest.raises(ValueError, match='immutable'):
            AdvancedJournalEntryManager.update_entry(
                entry.id, {'description': 'محاولة تعديل'}, owner_user.id)
        db.session.expire_all()
        assert _snapshot_entry(db.session.get(GLJournalEntry, entry.id)) == fingerprint

    def test_draft_line_replace_rebalances_headers(self, db, gl_accounts, owner_user):
        draft = self._draft(db, gl_accounts, owner_user)
        updated = AdvancedJournalEntryManager.update_entry(
            draft.id,
            {'lines': [
                {'account_code': '1120', 'debit': Decimal('80'), 'credit': Decimal('0')},
                {'account_code': '4100', 'debit': Decimal('0'), 'credit': Decimal('80')},
            ]},
            owner_user.id, reason='إعادة تصنيف')
        lines = updated.lines.all()
        assert len(lines) >= 2
        sum_dr = sum((Decimal(str(ln.debit or 0)) for ln in lines), Decimal('0'))
        sum_cr = sum((Decimal(str(ln.credit or 0)) for ln in lines), Decimal('0'))
        assert abs(sum_dr - sum_cr) <= TOLERANCE
        assert abs(Decimal(str(updated.total_debit)) - sum_dr) <= TOLERANCE
        assert abs(Decimal(str(updated.total_credit)) - sum_cr) <= TOLERANCE
        assert_ledger_invariants()

    def test_advanced_reverse_mirrors_links_and_freezes_original(
            self, db, gl_accounts, owner_user):
        entry = AdvancedJournalEntryManager.create_entry_with_validation(
            description='سيُعكس', lines=self.BALANCED, created_by=owner_user.id,
            reference_type='Adjustment', reference_id=42)
        fingerprint = _snapshot_entry(entry)

        reversal = AdvancedJournalEntryManager.reverse_entry_advanced(
            entry.id, owner_user.id, 'خطأ إدخال')

        assert reversal.entry_type == 'reversing'
        assert reversal.reference_type == 'Adjustment'
        assert reversal.reference_id == 42
        assert reversal.reversed_entry_id == entry.id

        db.session.expire_all()
        orig = db.session.get(GLJournalEntry, entry.id)
        assert orig.is_reversed is True
        assert orig.reversed_entry_id == reversal.id
        after = _snapshot_entry(orig)
        # Only the reversal flags may differ; financial content frozen.
        assert after[-1] == fingerprint[-1]
        assert after[1:-1] == fingerprint[1:-1]

        src_lines = sorted(orig.lines.all(), key=lambda ln: ln.account_id)
        rev_lines = sorted(reversal.lines.all(), key=lambda ln: ln.account_id)
        for src, rev in zip(src_lines, rev_lines):
            assert rev.debit == src.credit and rev.credit == src.debit
        assert_ledger_invariants()

    def test_double_reverse_rejected(self, db, gl_accounts, owner_user):
        entry = AdvancedJournalEntryManager.create_entry_with_validation(
            description='عكس مرة واحدة', lines=self.BALANCED,
            created_by=owner_user.id)
        AdvancedJournalEntryManager.reverse_entry_advanced(
            entry.id, owner_user.id, 'أول عكس')
        with pytest.raises(ValueError, match='مسبقاً'):
            AdvancedJournalEntryManager.reverse_entry_advanced(
                entry.id, owner_user.id, 'عكس ثانٍ')

    def test_approve_posts_draft_and_delete_rules_hold(self, db, gl_accounts, owner_user):
        draft = self._draft(db, gl_accounts, owner_user)
        approved = AdvancedJournalEntryManager.approve_entry(
            draft.id, owner_user.id, approval_notes='مراجعة')
        assert approved.is_posted is True
        with pytest.raises(ValueError, match='immutable'):
            AdvancedJournalEntryManager.delete_entry(approved.id, owner_user.id, 'سبب')

        draft2 = self._draft(db, gl_accounts, owner_user)
        assert AdvancedJournalEntryManager.delete_entry(
            draft2.id, owner_user.id, 'قيد زائد') is True
        assert db.session.get(GLJournalEntry, draft2.id) is None
        assert_ledger_invariants()


class TestImmutabilityAcrossSubsequentOperations:
    def test_payment_and_other_flows_never_touch_existing_posted_entries(
            self, db, owner_user, test_customer, test_product, warehouse):
        sale1 = SaleService.create_sale(
            customer=test_customer, seller=owner_user,
            lines_data=[{'product': test_product, 'quantity': Decimal('2'),
                         'unit_price': Decimal('55.000')}],
            warehouse_id=warehouse.id, currency='ILS',
            user_exchange_rate=Decimal('1'),
        )
        fingerprint = _snapshot_all()

        # Subsequent operation 1: pay sale1 (adds NEW Payment entries).
        SaleService.create_payment_for_sale(
            sale=sale1, amount=Decimal('55.000'),
            payment_method='cash', currency='ILS', exchange_rate=1.0)
        assert_snapshots_unchanged(fingerprint, 'after payment')

        # Subsequent operation 2: unrelated manual entry lifecycle.
        extra = AdvancedJournalEntryManager.create_entry_with_validation(
            description='قيد آخر', lines=[
                {'account_code': '1110', 'debit': Decimal('33'), 'credit': Decimal('0')},
                {'account_code': '4100', 'debit': Decimal('0'), 'credit': Decimal('33')},
            ], created_by=owner_user.id)
        assert_snapshots_unchanged(fingerprint, 'after manual entry')

        # Subsequent operation 3: reverse that unrelated entry.
        AdvancedJournalEntryManager.reverse_entry_advanced(
            extra.id, owner_user.id, 'تسوية')
        assert_snapshots_unchanged(fingerprint, 'after unrelated reversal')

        # Subsequent operation 4: create AND cancel a different sale.
        sale2 = SaleService.create_sale(
            customer=test_customer, seller=owner_user,
            lines_data=[{'product': test_product, 'quantity': Decimal('1'),
                         'unit_price': Decimal('70.000')}],
            warehouse_id=warehouse.id, currency='ILS',
            user_exchange_rate=Decimal('1'),
        )
        assert_snapshots_unchanged(fingerprint, 'after second sale')
        SaleService.cancel_sale(sale2)
        assert_snapshots_unchanged(fingerprint, 'after cancelling second sale')

        assert_ledger_invariants()

    def test_payment_entry_balanced_and_referenced(self, db, owner_user,
                                                   test_customer, test_product,
                                                   warehouse):
        sale = SaleService.create_sale(
            customer=test_customer, seller=owner_user,
            lines_data=[{'product': test_product, 'quantity': Decimal('1'),
                         'unit_price': Decimal('99.000')}],
            warehouse_id=warehouse.id, currency='ILS',
            user_exchange_rate=Decimal('1'),
        )
        payment = SaleService.create_payment_for_sale(
            sale=sale, amount=Decimal('40.000'),
            payment_method='bank_transfer', currency='ILS', exchange_rate=1.0)
        entry = GLJournalEntry.query.filter_by(
            reference_type='Payment', reference_id=payment.id).first()
        assert entry is not None
        lines = entry.lines.all()
        assert len(lines) == 2
        sum_dr = sum((Decimal(str(ln.debit or 0)) for ln in lines), Decimal('0'))
        sum_cr = sum((Decimal(str(ln.credit or 0)) for ln in lines), Decimal('0'))
        assert abs(sum_dr - sum_cr) <= TOLERANCE
        assert_ledger_invariants()
