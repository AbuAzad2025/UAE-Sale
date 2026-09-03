"""Unit tests for models/cost_center.py — labels, hierarchy, performance math."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal

from models import CostCenter, GLAccount, GLJournalEntry, GLJournalLine
from extensions import db as _db


def _make_center(**kw):
    args = dict(code='CC-1', name_ar='المركز الرئيسي', name_en='Main')
    args.update(kw)
    cc = CostCenter(**args)
    _db.session.add(cc)
    _db.session.flush()
    return cc


class TestLabels:
    def test_full_name_prefers_arabic(self, db):
        cc = _make_center()
        assert cc.full_name == 'CC-1 - المركز الرئيسي'

    def test_full_name_falls_back_to_english(self, db):
        # name_ar is NOT NULL at the DB level, so the English fallback only
        # applies to transient objects — build one without persisting.
        cc = CostCenter(code='CC-2', name_ar='مؤقت', name_en='Branch')
        cc.name_ar = None
        assert cc.full_name == 'CC-2 - Branch'

    def test_repr(self, db):
        assert 'CC-1' in repr(_make_center())

    @pytest.mark.parametrize('ctype,expected', [
        ('department', 'قسم'),
        ('branch', 'فرع'),
        ('project', 'مشروع'),
        ('product_line', 'خط إنتاج'),
        ('mystery', 'mystery'),
    ])
    def test_center_type_ar(self, db, ctype, expected):
        cc = _make_center(code=f'CC-{ctype}', center_type=ctype)
        assert cc.center_type_ar == expected

    def test_parent_children_hierarchy(self, db):
        parent = _make_center(code='P', name_ar='أب')
        child = _make_center(code='C', name_ar='ابن', parent_id=parent.id, level=1)
        assert child.parent.id == parent.id
        assert parent.children[0].id == child.id


def _seed_gl(db, center):
    rev = GLAccount(code='4000', name='Revenue', name_ar='إيراد', type='revenue')
    exp = GLAccount(code='5000', name='Expense', name_ar='مصروف', type='expense')
    _db.session.add_all([rev, exp])
    _db.session.flush()
    entry = GLJournalEntry(entry_number='JE-CC-1')
    _db.session.add(entry)
    _db.session.flush()
    _db.session.add_all([
        GLJournalLine(entry_id=entry.id, account_id=rev.id, credit=Decimal('1000'),
                      amount_base=Decimal('1000'), cost_center_id=center.id),
        GLJournalLine(entry_id=entry.id, account_id=exp.id, debit=Decimal('400'),
                      amount_base=Decimal('400'), cost_center_id=center.id),
    ])
    _db.session.commit()


class TestGetPerformance:
    def test_revenue_expense_profit_margin(self, db):
        cc = _make_center()
        _seed_gl(db, cc)
        perf = cc.get_performance()
        assert perf['revenues'] == pytest.approx(1000.0)
        assert perf['expenses'] == pytest.approx(400.0)
        assert perf['profit'] == pytest.approx(600.0)
        assert perf['margin'] == pytest.approx(60.0)

    def test_empty_center_zeroes_without_division_error(self, db):
        cc = _make_center(code='EMPTY', name_ar='فارغ')
        perf = cc.get_performance()
        assert perf == {'revenues': 0.0, 'expenses': 0.0,
                        'profit': 0.0, 'margin': 0}

    def test_period_filter(self, db):
        cc = _make_center()
        _seed_gl(db, cc)
        perf = cc.get_performance(period_start='2000-01-01', period_end='2000-12-31')
        assert perf['revenues'] == pytest.approx(0.0)
        assert perf['expenses'] == pytest.approx(0.0)

    def test_other_centers_excluded(self, db):
        cc = _make_center()
        _seed_gl(db, cc)
        other = _make_center(code='OTHER', name_ar='آخر')
        perf = other.get_performance()
        assert perf['revenues'] == pytest.approx(0.0)
