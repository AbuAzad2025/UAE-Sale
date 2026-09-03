"""Unit tests for models/fixed_asset.py — labels, depreciation math, post/dispose."""
import pytest
from datetime import date
from decimal import Decimal

from models import FixedAsset, GLAccount, DepreciationSchedule
from extensions import db as _db


def _account(code, name='Acc', atype='asset'):
    acc = GLAccount(code=code, name=name, name_ar=name, type=atype)
    _db.session.add(acc)
    _db.session.flush()
    return acc


def _asset(**kw):
    args = dict(asset_number='FA-1', name_ar='سيارة', purchase_date=date(2024, 1, 1),
                purchase_price=Decimal('12000'), salvage_value=Decimal('0'),
                useful_life_years=5, accumulated_depreciation=Decimal('0'),
                book_value=Decimal('12000'), status='active')
    args.update(kw)
    asset = FixedAsset(**args)
    _db.session.add(asset)
    _db.session.flush()
    return asset


def _wired_asset(db, **kw):
    asset_acc = _account('1500', 'Asset')
    dep_acc = _account('1501', 'AccumDep')
    exp_acc = _account('6100', 'DepExp', 'expense')
    asset = _asset(asset_account_id=asset_acc.id,
                   depreciation_account_id=dep_acc.id,
                   expense_account_id=exp_acc.id, **kw)
    _db.session.commit()
    return asset


class TestLabels:
    def test_repr(self, db):
        assert 'FA-1' in repr(_asset(asset_account_id=_account('1500').id))

    @pytest.mark.parametrize('cat,expected', [
        ('land', 'أراضي'), ('building', 'مباني'), ('vehicle', 'سيارات'),
        ('equipment', 'معدات'), ('furniture', 'أثاث'),
        ('computer', 'أجهزة كمبيوتر'), ('mystery', 'mystery'),
    ])
    def test_category_ar(self, db, cat, expected):
        a = _asset(asset_number=f'FA-{cat}', category=cat,
                   asset_account_id=_account(f'15{abs(hash(cat)) % 90 + 10}').id)
        assert a.category_ar == expected

    @pytest.mark.parametrize('status,expected', [
        ('active', 'نشط'), ('fully_depreciated', 'مستهلك بالكامل'),
        ('disposed', 'تم التخلص منه'), ('sold', 'تم بيعه'),
        ('mystery', 'mystery'),
    ])
    def test_status_ar(self, db, status, expected):
        a = _asset(asset_number=f'FA-{status}', status=status,
                   asset_account_id=_account(f'16{abs(hash(status)) % 90 + 10}').id)
        assert a.status_ar == expected


class TestDepreciationMath:
    def test_depreciable_and_remaining(self, db):
        a = _asset(asset_account_id=_account('1500').id)
        assert a.depreciable_amount == Decimal('12000')
        assert a.remaining_book_value == Decimal('12000')

    def test_land_never_depreciates(self, db):
        a = _asset(category='land', asset_account_id=_account('1500').id)
        assert a.calculate_monthly_depreciation() == Decimal('0')

    def test_straight_line(self, db):
        # 12000 / (5*12) = 200.00
        a = _asset(asset_account_id=_account('1500').id)
        assert a.calculate_monthly_depreciation() == Decimal('200.00')

    def test_declining_balance(self, db):
        a = _asset(depreciation_method='declining_balance',
                   asset_account_id=_account('1500').id)
        # rate 2/5=0.4; annual 12000*0.4=4800; monthly 400.00
        assert a.calculate_monthly_depreciation() == Decimal('400.00')

    def test_declining_stops_at_salvage(self, db):
        a = _asset(depreciation_method='declining_balance',
                   salvage_value=Decimal('11900'),
                   accumulated_depreciation=Decimal('100'),
                   book_value=Decimal('11900'),
                   asset_account_id=_account('1500').id)
        assert a.calculate_monthly_depreciation() == Decimal('0')

    def test_unknown_method_zero(self, db):
        a = _asset(depreciation_method='magic',
                   asset_account_id=_account('1500').id)
        assert a.calculate_monthly_depreciation() == Decimal('0')


class TestPostDepreciation:
    def test_posts_entry_and_schedule(self, db):
        a = _wired_asset(db)
        sched = a.post_depreciation(period_date=date(2026, 1, 1))
        assert isinstance(sched, DepreciationSchedule)
        assert sched.depreciation_amount == Decimal('200.00')
        assert a.accumulated_depreciation == Decimal('200.00')
        assert a.book_value == Decimal('11800.00')
        assert a.last_depreciation_date == date(2026, 1, 1)

    def test_duplicate_period_rejected(self, db):
        a = _wired_asset(db)
        a.post_depreciation(period_date=date(2026, 2, 1))
        with pytest.raises(ValueError, match='مسبقاً'):
            a.post_depreciation(period_date=date(2026, 2, 1))

    def test_inactive_rejected(self, db):
        a = _wired_asset(db, status='disposed')
        with pytest.raises(ValueError, match='غير نشط'):
            a.post_depreciation(period_date=date(2026, 3, 1))

    def test_land_returns_none(self, db):
        a = _wired_asset(db, category='land')
        assert a.post_depreciation(period_date=date(2026, 4, 1)) is None

    def test_full_depreciation_flips_status(self, db):
        a = _wired_asset(db, purchase_price=Decimal('200'),
                         salvage_value=Decimal('0'),
                         accumulated_depreciation=Decimal('196.67'),
                         book_value=Decimal('3.33'))
        a.post_depreciation(period_date=date(2026, 5, 1))
        assert a.status == 'fully_depreciated'


class TestDispose:
    def _sellable(self, db):
        for code in ['1120', '4500', '6990']:
            if not GLAccount.query.filter_by(code=code).first():
                _account(code, f'A{code}')
        return _wired_asset(db)

    def test_sell_records_gain(self, db):
        a = self._sellable(db)
        a.dispose(date(2026, 6, 1), Decimal('13000'), notes='sold ok')
        assert a.status == 'sold'
        assert a.disposal_gain_loss == Decimal('1000')
        assert 'sold ok' in (a.notes or '')

    def test_scrap_records_disposed(self, db):
        a = self._sellable(db)
        a.dispose(date(2026, 6, 2), Decimal('0'))
        assert a.status == 'disposed'
        assert a.disposal_gain_loss == Decimal('-12000')

    def test_double_dispose_rejected(self, db):
        a = self._sellable(db)
        a.dispose(date(2026, 6, 3), Decimal('0'))
        with pytest.raises(ValueError, match='مسبقاً'):
            a.dispose(date(2026, 6, 4), Decimal('0'))
