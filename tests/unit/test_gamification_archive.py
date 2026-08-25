import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

import pytest

from models import ArchivedRecord, Customer, ProductCategory, Role, Sale, User
from services.archive_service import ArchiveService
from services.gamification_service import GamificationService


def naive_utc(**kwargs):
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).replace(tzinfo=None)


@pytest.fixture
def staff_role(db):
    role = Role(name='Staff', name_ar='موظف', slug='gamification-staff')
    db.session.add(role)
    db.session.commit()
    return role


def make_user(db, role, username, **kw):
    params = dict(
        username=username, email=f'{username}@test.com',
        full_name=username.title(), is_owner=False, is_active=True,
        role_id=role.id,
    )
    params.update(kw)
    user = User(**params)
    user.set_password('Secret@12345')
    db.session.add(user)
    db.session.commit()
    return user


def make_customer(db, name):
    customer = Customer(
        name=name, name_ar='زبون أرشيف', customer_type='regular',
        phone='+971500000000', credit_limit=Decimal('0'),
        balance=Decimal('0'), is_active=True,
    )
    db.session.add(customer)
    db.session.commit()
    return customer


def make_minimal_sale(db, customer, seller, number, amount):
    sale = Sale(
        sale_number=number, customer_id=customer.id, seller_id=seller.id,
        total_amount=Decimal(amount), amount_base=Decimal(amount),
        paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
        balance_due=Decimal(amount), currency='AED',
        exchange_rate=Decimal('1'), payment_status='unpaid',
        status='confirmed', is_active=True,
    )
    db.session.add(sale)
    db.session.commit()
    return sale


class TestBadgeThresholds:

    @pytest.mark.parametrize('points,expected_key', [
        (0, 'newbie'),
        (99, 'newbie'),
        (100, 'bronze'),
        (499, 'bronze'),
        (500, 'silver'),
        (999, 'silver'),
        (1000, 'gold'),
        (4999, 'gold'),
        (5000, 'platinum'),
        (9999, 'platinum'),
        (10000, 'legend'),
        (999999, 'legend'),
    ])
    def test_exact_thresholds(self, points, expected_key):
        badge = GamificationService.get_user_badge(points)
        assert badge['key'] == expected_key
        assert badge['min_points'] == GamificationService.BADGES[expected_key]['points']

    def test_badge_payload_shape(self):
        badge = GamificationService.get_user_badge(1000)
        assert set(badge.keys()) == {'key', 'name_ar', 'icon', 'min_points'}
        assert badge['name_ar'] == GamificationService.BADGES['gold']['name_ar']

    def test_negative_points_falls_back_to_newbie(self):
        badge = GamificationService.get_user_badge(-1)
        assert badge['name_ar'] == GamificationService.BADGES['newbie']['name_ar']


class TestAwardPoints:

    def test_user_not_found(self, db):
        result = GamificationService.award_points(999999, 'sale_created')
        assert result == {'success': False, 'error': 'User not found'}

    def test_known_action_awards_config_points(self, db, staff_role):
        user = make_user(db, staff_role, 'earner1')
        result = GamificationService.award_points(user.id, 'payment_collected')
        assert result['success'] is True
        assert result['points_awarded'] == 5
        assert result['total_points'] == 5
        assert result['badge']['key'] == 'newbie'
        assert result['level_up'] is False

    def test_unknown_action_awards_zero(self, db, staff_role):
        user = make_user(db, staff_role, 'earner2')
        result = GamificationService.award_points(user.id, 'hacked_action')
        assert result['points_awarded'] == 0
        assert result['total_points'] == 0

    @pytest.mark.parametrize('amount,expected_points', [
        (Decimal('15000'), 50),
        (Decimal('10001'), 50),
        (Decimal('10000'), 30),
        (Decimal('8000'), 30),
        (Decimal('5001'), 30),
        (Decimal('5000'), 20),
        (Decimal('3000'), 20),
    ])
    def test_large_sale_amount_tiers(self, db, staff_role, amount, expected_points):
        user = make_user(db, staff_role, f'large{int(expected_points)}{int(amount)}')
        result = GamificationService.award_points(
            user.id, 'large_sale', {'amount': amount}
        )
        assert result['points_awarded'] == expected_points

    def test_large_sale_without_metadata_uses_default(self, db, staff_role):
        user = make_user(db, staff_role, 'largedefault')
        result = GamificationService.award_points(user.id, 'large_sale', None)
        assert result['points_awarded'] == 20

    def test_level_up_crosses_bronze_boundary(self, db, staff_role):
        user = make_user(db, staff_role, 'riser1')
        user.points = 95
        db.session.commit()
        result = GamificationService.award_points(user.id, 'sale_created')
        assert result['level_up'] is True
        assert result['badge']['key'] == 'bronze'
        assert result['total_points'] == 105

    def test_exact_threshold_reach_counts_as_level_up(self, db, staff_role):
        user = make_user(db, staff_role, 'riser2')
        user.points = 90
        db.session.commit()
        result = GamificationService.award_points(user.id, 'sale_created')
        assert result['total_points'] == 100
        assert result['level_up'] is True
        assert result['badge']['key'] == 'bronze'

    def test_same_tier_award_is_not_level_up(self, db, staff_role):
        user = make_user(db, staff_role, 'riser3')
        user.points = 50
        db.session.commit()
        result = GamificationService.award_points(user.id, 'sale_created')
        assert result['level_up'] is False
        assert result['badge']['key'] == 'newbie'

    def test_points_accumulate_across_actions(self, db, staff_role):
        user = make_user(db, staff_role, 'accumulator')
        first = GamificationService.award_points(user.id, 'customer_added')
        second = GamificationService.award_points(user.id, 'product_added')
        assert first['total_points'] == 3
        assert second['total_points'] == 5
        assert second['level_up'] is False


class TestLeaderboard:

    def test_excludes_owner_and_inactive_users(self, db, staff_role):
        seller = make_user(db, staff_role, 'lb_seller')
        make_user(db, staff_role, 'lb_owner', is_owner=True)
        make_user(db, staff_role, 'lb_inactive', is_active=False)
        seller.points = 300
        board = GamificationService.get_leaderboard()
        names = [entry['username'] for entry in board]
        assert 'lb_owner' not in names
        assert 'lb_inactive' not in names
        assert 'lb_seller' in names

    def test_ranking_order_ranks_and_badges(self, db, staff_role):
        seller = make_user(db, staff_role, 'rank_seller')
        manager = make_user(db, staff_role, 'rank_manager')
        manager.full_name_ar = 'المدير العام'
        db.session.commit()
        seller.points = 300
        manager.points = 1200
        board = GamificationService.get_leaderboard(limit=10)
        assert [e['rank'] for e in board] == list(range(1, len(board) + 1))
        by_name = {e['username']: e for e in board}
        assert by_name['rank_seller']['points'] == 300
        assert by_name['rank_seller']['badge']['key'] == 'bronze'
        assert by_name['rank_manager']['points'] == 1200
        assert by_name['rank_manager']['badge']['key'] == 'gold'
        assert by_name['rank_manager']['full_name'] == 'المدير العام'
        assert by_name['rank_seller']['full_name'] == 'Rank_Seller'

    def test_tie_break_keeps_stable_id_order(self, db, staff_role):
        first = make_user(db, staff_role, 'tie_first')
        second = make_user(db, staff_role, 'tie_second')
        first.points = 700
        second.points = 700
        board = GamificationService.get_leaderboard(limit=10)
        duo = [e for e in board if e['username'].startswith('tie_')]
        assert [e['username'] for e in duo] == ['tie_first', 'tie_second']
        assert [e['rank'] for e in duo] == [duo[0]['rank'], duo[0]['rank'] + 1]

    def test_limit_trims_board(self, db, staff_role):
        make_user(db, staff_role, 'limit_a')
        make_user(db, staff_role, 'limit_b')
        make_user(db, staff_role, 'limit_c')
        board = GamificationService.get_leaderboard(limit=2)
        assert len(board) == 2
        assert board[0]['username'] == 'limit_a'

    def test_zero_points_user_listed_with_newbie(self, db, staff_role):
        make_user(db, staff_role, 'fresh_guy')
        entry = next(
            e for e in GamificationService.get_leaderboard()
            if e['username'] == 'fresh_guy'
        )
        assert entry['points'] == 0
        assert entry['badge']['key'] == 'newbie'


class TestUserStats:

    def test_stats_count_all_sales_but_sum_confirmed_only(self, db, staff_role, test_customer):
        seller = make_user(db, staff_role, 'stats_seller')
        make_minimal_sale(db, test_customer, seller, 'S-ST-0001', '250.500')
        make_minimal_sale(db, test_customer, seller, 'S-ST-0002', '100.000')
        cancelled = make_minimal_sale(db, test_customer, seller, 'S-ST-0003', '999.000')
        cancelled.status = 'cancelled'
        db.session.commit()
        seller.points = 145
        stats = GamificationService.get_user_stats(seller.id)
        assert stats['success'] is True
        assert stats['points'] == 145
        assert stats['total_sales'] == 3
        assert stats['total_amount'] == 350.5
        assert stats['current_badge']['key'] == 'bronze'
        assert stats['next_badge']['points'] == 500
        assert stats['points_to_next'] == 355

    def test_stats_top_tier_has_no_next_badge(self, db, staff_role):
        user = make_user(db, staff_role, 'legend_user')
        user.points = 12000
        stats = GamificationService.get_user_stats(user.id)
        assert stats['next_badge'] is None
        assert stats['points_to_next'] == 0
        assert stats['current_badge']['key'] == 'legend'
        assert stats['total_sales'] == 0
        assert stats['total_amount'] == 0.0

    def test_stats_unknown_user(self, db):
        assert GamificationService.get_user_stats(424242) == {'success': False}


class TestArchiveRecord:

    def test_persists_reason_and_snapshot_anonymous(self, app, db):
        customer = make_customer(db, 'عميل الأرشيف')
        with app.test_request_context('/'):
            archived = ArchiveService.archive_record(
                'Customer', customer, reason='تنظيف نهاية السنة'
            )
        assert archived.table_name == 'Customer'
        assert archived.record_id == customer.id
        assert archived.reason == 'تنظيف نهاية السنة'
        assert archived.can_restore is True
        assert archived.archived_by is None
        assert archived.archived_at is not None
        assert archived.data['name'] == 'عميل الأرشيف'
        assert archived.data['id'] == customer.id

    def test_archived_by_authenticated_user(self, app, db, staff_role):
        user = make_user(db, staff_role, 'archiver')
        customer = make_customer(db, 'Cust By Auth')
        fake_current = types.SimpleNamespace(id=user.id, is_authenticated=True)
        with mock.patch('services.archive_service.current_user', fake_current):
            archived = ArchiveService.archive_record('Customer', customer, reason='who')
        assert archived.archived_by == user.id

    def test_sale_to_dict_snapshot(self, app, db, staff_role, test_customer):
        seller = make_user(db, staff_role, 'sale_archiver')
        sale = make_minimal_sale(db, test_customer, seller, 'S-ARC-0001', '750.000')
        with app.test_request_context('/'):
            archived = ArchiveService.archive_record('Sale', sale, reason='retention')
        assert archived.data['sale_number'] == 'S-ARC-0001'
        assert archived.data['total_amount'] == 750.0
        assert archived.data['status'] == 'confirmed'

    def test_commit_false_defers_write(self, app, db):
        customer = make_customer(db, 'Deferred Cust')
        with app.test_request_context('/'):
            ArchiveService.archive_record('Customer', customer, commit=False)
            assert ArchivedRecord.query.count() == 1
        db.session.rollback()
        assert ArchivedRecord.query.count() == 0

    def test_columns_fallback_serializes_datetimes(self, app, db):
        category = ProductCategory(name='أرشيف فئة', is_active=True)
        db.session.add(category)
        db.session.commit()
        with app.test_request_context('/'):
            archived = ArchiveService.archive_record(
                'ProductCategory', category, reason='legacy table'
            )
        assert isinstance(archived.data['created_at'], str)
        assert archived.data['name'] == 'أرشيف فئة'
        assert archived.data['id'] == category.id
        fetched = db.session.get(ArchivedRecord, archived.id)
        assert fetched.data['is_active'] is True

    def test_failure_raises_and_leaves_no_row(self, app, db):
        class Broken:
            id = 31337

            def to_dict(self):
                raise ValueError('snapshot exploded')

        with app.test_request_context('/'):
            with pytest.raises(ValueError):
                ArchiveService.archive_record('Sale', Broken(), reason='bad')
        assert ArchivedRecord.query.count() == 0


class TestSoftDeleteAndRestore:

    def test_soft_delete_hides_from_active_then_restore_returns_it(self, app, db):
        customer = make_customer(db, 'Cycle Cust')
        with app.test_request_context('/'):
            archived = ArchiveService.archive_record('Customer', customer, reason='hide')
            ArchiveService.soft_delete(customer)
        assert customer.is_active is False
        assert Customer.query.filter_by(is_active=True).count() == 0
        restored = ArchiveService.restore_record(archived)
        assert restored.is_active is True
        assert Customer.query.filter_by(is_active=True).count() == 1
        assert restored.id == customer.id

    def test_restore_unknown_model_raises_value_error(self, app, db):
        ghost = ArchivedRecord(table_name='NotAModel', record_id=1, data={})
        with pytest.raises(ValueError, match='Model not found'):
            ArchiveService.restore_record(ghost)

    def test_restore_when_record_deleted_raises(self, app, db):
        category = ProductCategory(name='Doomed Cat')
        db.session.add(category)
        db.session.commit()
        with app.test_request_context('/'):
            archived = ArchiveService.archive_record('ProductCategory', category)
            db.session.delete(category)
            db.session.commit()
            with pytest.raises(ValueError, match='Record not found in database'):
                ArchiveService.restore_record(archived)


class TestHardDelete:

    def test_archives_before_removal_with_reason(self, app, db):
        category = ProductCategory(name='Hard Cat')
        db.session.add(category)
        db.session.commit()
        with app.test_request_context('/'):
            ArchiveService.hard_delete('ProductCategory', category)
        assert db.session.get(ProductCategory, category.id) is None
        rows = ArchiveService.get_archived_records(table_name='ProductCategory')
        assert len(rows) == 1
        assert rows[0].reason == 'Hard Delete'
        assert rows[0].record_id == category.id
        assert rows[0].data['name'] == 'Hard Cat'

    def test_can_skip_archiving(self, app, db):
        category = ProductCategory(name='Vanishing Cat')
        db.session.add(category)
        db.session.commit()
        with app.test_request_context('/'):
            ArchiveService.hard_delete('ProductCategory', category, archive_first=False)
        assert db.session.get(ProductCategory, category.id) is None
        assert ArchivedRecord.query.count() == 0


class TestArchivedQueriesAndCleanup:

    def test_listing_filters_by_table_and_orders_newest_first(self, db):
        old = ArchivedRecord(table_name='Customer', record_id=1, data={'n': 1})
        old.archived_at = naive_utc(days=5)
        new = ArchivedRecord(table_name='Customer', record_id=2, data={'n': 2})
        new.archived_at = naive_utc(hours=1)
        other = ArchivedRecord(table_name='ProductCategory', record_id=3, data={'n': 3})
        other.archived_at = naive_utc(minutes=10)
        db.session.add_all([old, new, other])
        db.session.commit()

        customers = ArchiveService.get_archived_records(table_name='Customer')
        assert [r.record_id for r in customers] == [2, 1]

        limited = ArchiveService.get_archived_records(table_name='Customer', limit=1)
        assert [r.record_id for r in limited] == [2]

        everything = ArchiveService.get_archived_records()
        assert len(everything) == 3

    def test_cleanup_only_removes_old_non_restorable(self, db):
        combos = [
            (naive_utc(days=400), False),
            (naive_utc(days=400), True),
            (naive_utc(days=10), False),
            (naive_utc(days=10), True),
        ]
        for idx, (ts, restorable) in enumerate(combos):
            row = ArchivedRecord(table_name=f'tbl{idx}', record_id=idx + 1, data={'i': idx})
            row.archived_at = ts
            row.can_restore = restorable
            db.session.add(row)
        db.session.commit()

        removed = ArchiveService.cleanup_old_archives(days=365)
        assert removed == 1
        survivors = {r.table_name for r in ArchivedRecord.query.all()}
        assert survivors == {'tbl1', 'tbl2', 'tbl3'}
