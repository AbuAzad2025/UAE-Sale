"""توزيع أرباح الشركاء — المنتج (فوري) والشركة (دوري).

يغطي:
* الترحيل الفوري لحصة شريك المنتج مع الفاتورة (ربح وخسارة).
* العكس التناسبي مع المرتجع.
* العكس الكامل مع إلغاء الفاتورة.
* معاينة التوزيع الدوري للشركة وترحيله (ربح وخسارة) مع خصم المسحوبات والمبيعات.
* منع التوزيع المكرر لنفس الفترة (idempotent).
"""
from decimal import Decimal
from datetime import date

import pytest

from models import Customer, GLJournalEntry, GLJournalLine, ProductPartner, SaleLine


@pytest.fixture
def gl_accounts(app):
    with app.app_context():
        from services.gl_service import GLService
        GLService.ensure_core_accounts()


@pytest.fixture
def partner_customer(db):
    partner = Customer(
        name='شريك تجريبي', name_ar='شريك تجريبي',
        customer_type='partner', partner_scope='product',
        is_active=True, phone='+971500000001',
    )
    db.session.add(partner)
    db.session.commit()
    return partner


@pytest.fixture
def company_partner(db):
    partner = Customer(
        name='شريك الشركة', name_ar='شريك الشركة',
        customer_type='partner', partner_scope='company',
        partner_share=Decimal('25.000'), is_active=True,
        phone='+971500000002',
    )
    db.session.add(partner)
    db.session.commit()
    return partner


def _make_sale(db, owner_user, test_customer, test_product, *, qty="2", price="100.000",
               cost=None, discount=None, unit_price=None):
    from services.sale_service import SaleService

    if cost is not None:
        test_product.average_cost = Decimal(cost)
        test_product.cost_price = Decimal(cost)
        db.session.commit()

    sale = SaleService.create_sale(
        customer=test_customer,
        seller=owner_user,
        lines_data=[{
            'product': test_product,
            'quantity': Decimal(qty),
            'unit_price': Decimal(unit_price or price),
            'tax_treatment': 'exempt',
        }],
        currency='AED',
        user_exchange_rate='1',
    )
    if discount is not None:
        sale.discount_amount = Decimal(discount)
        db.session.commit()
    return sale


def _partner_lines(db, partner_id):
    """أسطر القيود على جاري الشريك (3350) الخاصة بشريك بعينه — لقياس ما تدين به الشركة للشريك."""
    from models import GLAccount
    return (GLJournalLine.query
            .join(GLJournalEntry, GLJournalEntry.id == GLJournalLine.entry_id)
            .join(GLAccount, GLAccount.id == GLJournalLine.account_id)
            .filter(GLJournalLine.party_id == partner_id,
                    GLAccount.code == '3350',
                    GLJournalEntry.is_reversed.is_(False)))


class TestProductPartnerShares:
    """شريك المنتج: يُرحَّل مع الفاتورة فورًا ويعكسه المرتجع/الإلغاء."""

    def test_profit_share_posted_immediately_with_sale(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('25.00'),
        ))
        db.session.commit()

        sale = _make_sale(db, owner_user, test_customer, test_product, qty='2', price='100',
                          cost='30')

        lines = _partner_lines(db, partner_customer.id).all()
        assert lines, 'يجب أن تُرحَّل حصة الشريك مع الفاتورة نفسها'
        net_owed = sum(l.credit - l.debit for l in lines)
        assert net_owed == Decimal('35.000')  # (200 - 60) * 25%

        entry = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id,
        ).filter(GLJournalEntry.description.like('Partner profit shares%')).first()
        assert entry is not None
        assert entry.total_debit == entry.total_credit

    def test_loss_is_distributed_too(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('50.00'),
        ))
        db.session.commit()

        sale = _make_sale(db, owner_user, test_customer, test_product, qty='1',
                          price='40', cost='100')

        lines = _partner_lines(db, partner_customer.id).all()
        assert lines
        net_owed = sum(l.credit - l.debit for l in lines)
        # الخسارة تُحسم من الشريك: جاري الشريك مدين (ينقص رصيده الجاري)
        assert net_owed == Decimal('-30.000')

    def test_cancel_reverses_partner_shares(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('25.00'),
        ))
        db.session.commit()

        sale = _make_sale(db, owner_user, test_customer, test_product, qty='2', price='100',
                          cost='30')
        from services.sale_service import SaleService
        SaleService.cancel_sale(sale)

        still_active = _partner_lines(db, partner_customer.id).all()
        net = sum(l.credit - l.debit for l in still_active)
        assert net == Decimal('0.000')

    def test_partial_return_reverses_proportionally(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('25.00'),
        ))
        db.session.commit()

        sale = _make_sale(db, owner_user, test_customer, test_product, qty='2', price='100',
                          cost='30')
        line = SaleLine.query.filter_by(sale_id=sale.id).first()

        from services.return_service import ReturnService
        ReturnService.create_return(
            sale.id,
            [{'sale_line_id': line.id, 'quantity': Decimal('1'), 'condition': 'good'}],
            user_id=owner_user.id,
        )

        net = sum(l.credit - l.debit for l in _partner_lines(db, partner_customer.id).all())
        # رُجِع نصف السطر: يبقى نصف الحصة (نصف الـ 140 التشريحية)
        assert net == Decimal('17.500')

        ret_entries = GLJournalEntry.query.filter_by(reference_type='ProductReturn').all()
        partner_revs = [e for e in ret_entries
                        if 'Reverse partner profit shares' in (e.description or '')]
        assert partner_revs, 'المرتجع يجب أن يرحل عكسًا تناسبيًا لحصص الشركاء'


class TestCompanyPartnerDistribution:
    """شريك الشركة: صافي نتيجة الشركة تُحسب دوريًا وتُوزَّع بعد خصم المسحوبات والمبيعات."""

    def _post_revenue(self, app, amount, db, entry_date=None):
        from datetime import datetime
        from services.gl_service import GLService
        from services.account_resolution import AccountResolver, AccountRole
        GLService.post_entry(
            [{'account': AccountResolver.resolve(AccountRole.CASH),
              'debit': Decimal(str(amount)), 'description': 'إيراد اختباري'},
             {'account': AccountResolver.resolve(AccountRole.SALES_REVENUE),
              'credit': Decimal(str(amount)), 'description': 'إيراد اختباري'}],
            description='إيراد اختباري لتوزيع الأرباح',
            reference_type='Test',
            exchange_rate=Decimal('1'),
            entry_date=datetime(entry_date.year, entry_date.month, entry_date.day)
            if entry_date else None,
        )
        db.session.commit()

    def _post_expense(self, app, amount, db, entry_date=None):
        from datetime import datetime
        from services.gl_service import GLService
        from services.account_resolution import AccountResolver, AccountRole
        GLService.post_entry(
            [{'account': AccountResolver.resolve(AccountRole.SALARY_EXPENSE),
              'debit': Decimal(str(amount)), 'description': 'مصروف اختباري'},
             {'account': AccountResolver.resolve(AccountRole.CASH),
              'credit': Decimal(str(amount)), 'description': 'مصروف اختباري'}],
            description='مصروف اختباري لتوزيع الأرباح',
            reference_type='Test',
            exchange_rate=Decimal('1'),
            entry_date=datetime(entry_date.year, entry_date.month, entry_date.day)
            if entry_date else None,
        )
        db.session.commit()

    def test_preview_and_distribute_profit(
            self, db, app, company_partner, gl_accounts):
        from services import partner_profit as pp

        self._post_revenue(app, '1000', db)
        preview = pp.preview_partner_distributions(None, None)
        row = next(r for r in preview if r['partner_id'] == company_partner.id)
        assert row['partner_share_pct'] == Decimal('25.000')
        assert row['share_amount'] == Decimal('250.000')
        assert row['net_payout'] == Decimal('250.000')

        entry = pp.post_partner_distributions(None, None)
        assert entry is not None
        assert entry.total_debit == entry.total_credit == Decimal('1000.000')

        partner_lines = [l for l in entry.lines if l.party_id == company_partner.id]
        assert partner_lines and all(l.credit == Decimal('250.000') for l in partner_lines)

        # نفس الفترة لا تُرحَّل مرتين
        assert pp.post_partner_distributions(None, None) is None

    def test_draws_are_deducted(
            self, db, app, company_partner, gl_accounts):
        from services import partner_profit as pp

        self._post_revenue(app, '1000', db)
        draw = pp.post_partner_draw(company_partner.id, Decimal('100'))
        assert draw is not None

        preview = pp.preview_partner_distributions(None, None)
        row = next(r for r in preview if r['partner_id'] == company_partner.id)
        assert row['draws_deducted'] == Decimal('100.000')
        assert row['net_payout'] == Decimal('150.000')

        entry = pp.post_partner_distributions(None, None)
        partner_lines = [l for l in entry.lines if l.party_id == company_partner.id]
        assert all(l.credit == Decimal('150.000') for l in partner_lines)

    def test_loss_is_allocated_between_partners(
            self, db, app, company_partner, gl_accounts):
        from services import partner_profit as pp

        self._post_revenue(app, '1000', db)
        self._post_expense(app, '1600', db)   # صافي -600

        preview = pp.preview_partner_distributions(None, None)
        row = next(r for r in preview if r['partner_id'] == company_partner.id)
        assert row['share_amount'] == Decimal('-150.000')
        assert row['net_payout'] == Decimal('-150.000')

        entry = pp.post_partner_distributions(None, None)
        assert entry is not None
        assert entry.total_debit == entry.total_credit == Decimal('600.000')
        partner_lines = [l for l in entry.lines if l.party_id == company_partner.id]
        # الخسارة تُحمَّل على الشريك: مدين 3350
        assert partner_lines and all(l.debit == Decimal('150.000') for l in partner_lines)

    def test_partner_percentages_above_100_rejected(self, db, app, gl_accounts):
        from services import partner_profit as pp

        for i, pct in enumerate(('60', '55')):
            p = Customer(
                name=f'شريك {i}', name_ar=f'شريك {i}',
                customer_type='partner', partner_scope='company',
                partner_share=Decimal(f'{pct}.000'), is_active=True,
                phone=f'+9715999990{i}',
            )
            db.session.add(p)
        db.session.commit()

        self._post_revenue(app, '1000', db)
        with pytest.raises(ValueError, match='100'):
            pp.post_partner_distributions(None, None)

    def test_zero_net_income_posts_nothing(self, db, app, company_partner, gl_accounts):
        from services import partner_profit as pp

        assert pp.post_partner_distributions(None, None) is None


class TestDualRoleAndBoundaries:
    """شريك ذو دورين (منتج + شركة) وحالات الحدود."""

    def _make_company_product_partner(self, db, partner):
        partner.partner_scope = 'company'
        partner.partner_share = Decimal('25.000')
        partner.customer_type = 'partner'
        db.session.commit()

    def test_dual_role_gets_both_shares_without_double_counting(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        from services import partner_profit as pp
        from services.sale_service import SaleService

        self._make_company_product_partner(db, partner_customer)
        test_product.average_cost = Decimal('30')
        test_product.cost_price = Decimal('30')
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('25.00'),
        ))
        db.session.commit()

        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('2'),
                'unit_price': Decimal('100'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
        )

        net = pp.compute_net_income(None, None)
        # 200 إيراد - 60 تكلفة - 35 حصة المنتج (6910) = 105
        assert net == Decimal('105.000')

        row = next(r for r in pp.preview_partner_distributions(None, None)
                   if r['partner_id'] == partner_customer.id)
        assert row['share_amount'] == Decimal('26.250')
        assert row['product_shares_in_period'] == Decimal('35.000')
        assert row['total_entitlement'] == Decimal('61.250')

        entry = pp.post_partner_distributions(None, None)
        partner_lines = [l for l in entry.lines if l.party_id == partner_customer.id]
        assert partner_lines and all(l.credit == Decimal('26.250') for l in partner_lines)

        # إجمالي ما استحقه الشريك (قيد المنتج + قيد الشركة) — كل أساس مستقل
        total_current = sum(l.credit - l.debit
                            for l in _partner_lines(db, partner_customer.id).all())
        assert total_current == Decimal('61.250')

    def test_scope_none_partner_still_earns_product_shares(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        """partner_scope='none' لا يمحو روابط المنتج — توزيع المنتج يعمل دائمًا."""
        from services.sale_service import SaleService

        partner_customer.partner_scope = 'none'
        partner_customer.customer_type = 'partner'
        test_product.average_cost = Decimal('30')
        test_product.cost_price = Decimal('30')
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('50.00'),
        ))
        db.session.commit()

        SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('1'),
                'unit_price': Decimal('100'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
        )
        net_owed = sum(l.credit - l.debit for l in _partner_lines(db, partner_customer.id).all())
        assert net_owed == Decimal('35.000')  # (100-30) * 50%

    def test_full_paid_sale_not_deducted_and_unpaid_deducted(
            self, db, owner_user, test_product, company_partner, gl_accounts):
        """المبيعات للشريك: كاملة الدفع = لا خصم، غير مسددة = كل المبلغ، جزئية = الباقي."""
        from services.sale_service import SaleService
        from services import partner_profit as pp

        test_product.average_cost = Decimal('30')
        test_product.cost_price = Decimal('30')
        db.session.commit()

        # 1) غير مسددة
        sale1 = SaleService.create_sale(
            customer=company_partner,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('3'),
                'unit_price': Decimal('50'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
        )
        assert pp._sales_to_partner(company_partner.id) == Decimal('150.000')

        # إلغاء الفاتورة الأولى لإخراجها من حساب المبيعات (الاستبعاد صحيح)
        SaleService.cancel_sale(sale1)
        assert pp._sales_to_partner(company_partner.id) == Decimal('0.000')

        # 2) مسددة بالكامل
        SaleService.create_sale(
            customer=company_partner,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('3'),
                'unit_price': Decimal('50'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
            payment_data={'amount': Decimal('150'), 'payment_method': 'cash'},
        )
        assert pp._sales_to_partner(company_partner.id) == Decimal('0.000')

        # 3) جزئية الدفع
        SaleService.create_sale(
            customer=company_partner,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('3'),
                'unit_price': Decimal('50'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
            payment_data={'amount': Decimal('50'), 'payment_method': 'cash'},
        )
        assert pp._sales_to_partner(company_partner.id) == Decimal('100.000')


class TestOverlappingDistributionPeriods:
    """حظر تداخل الفترات — الربح لا يُوزَّع مرتين."""

    def _revenue(self, db, day, amount='800'):
        from datetime import datetime
        from services.gl_service import GLService
        from services.account_resolution import AccountResolver, AccountRole
        GLService.post_entry(
            [{'account': AccountResolver.resolve(AccountRole.CASH),
              'debit': Decimal(str(amount)), 'description': 'd'},
             {'account': AccountResolver.resolve(AccountRole.SALES_REVENUE),
              'credit': Decimal(str(amount)), 'description': 'd'}],
            description='إيراد', reference_type='Test',
            exchange_rate=Decimal('1'),
            entry_date=datetime(day.year, day.month, day.day))
        db.session.commit()

    def test_overlapping_periods_rejected_idempotent_exact_repeat(
            self, db, app, gl_accounts):
        from datetime import date as _d

        self._revenue(db, _d(2026, 3, 10))

        p = Customer(
            name='شريك مارس', name_ar='شريك مارس',
            customer_type='partner', partner_scope='company',
            partner_share=Decimal('50.000'), is_active=True,
        )
        db.session.add(p)
        db.session.commit()

        from services import partner_profit as pp
        first = pp.post_partner_distributions(_d(2026, 3, 1), _d(2026, 3, 31))
        assert first is not None
        # Entry لا يُكرر نفس الفترة
        assert pp.post_partner_distributions(_d(2026, 3, 1), _d(2026, 3, 31)) is None
        # فترة متداخلة ترفع ValueError
        with pytest.raises(ValueError, match='متداخل'):
            pp.post_partner_distributions(_d(2026, 3, 15), _d(2026, 4, 30))

        # فترة متجاورة غير متداخلة تمر
        self._revenue(db, _d(2026, 4, 15))
        third = pp.post_partner_distributions(_d(2026, 4, 1), _d(2026, 4, 30))
        assert third is not None


class TestPreviewShowsTotalEntitlement:
    def test_preview_exposes_product_accrual_and_total(
            self, db, app, company_partner, gl_accounts, test_customer, test_product, owner_user):
        from services import partner_profit as pp
        from services.sale_service import SaleService

        company_partner.partner_scope = 'company'
        company_partner.partner_share = Decimal('30.000')
        test_product.average_cost = Decimal('20')
        test_product.cost_price = Decimal('20')
        db.session.commit()
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=company_partner.id,
            percentage=Decimal('20.00'),
        ))
        db.session.commit()

        SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('1'),
                'unit_price': Decimal('100'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
        )

        row = next(r for r in pp.preview_partner_distributions(None, None)
                   if r['partner_id'] == company_partner.id)
        assert row['product_shares_in_period'] == Decimal('16.000')
        assert row['net_payout'] >= Decimal('0')
        assert row['total_entitlement'] == row['net_payout'] + row['product_shares_in_period']


class TestInclusiveVatProductShare:
    """شامل الضريبة يُحسم من أساس ربح الشريك (لا تدفع ضريبة من ربحه)."""

    def test_inclusive_vat_deducted_from_partner_base(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        from services.sale_service import SaleService

        partner_customer.partner_scope = 'product'
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('25.00'),
        ))
        test_product.average_cost = Decimal('30')
        test_product.cost_price = Decimal('30')
        test_product.tax_treatment = 'standard'
        db.session.commit()

        SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('1'),
                'unit_price': Decimal('105'),   # شامل 5%
            }],
            currency='AED',
            user_exchange_rate='1',
            tax_rate=Decimal('5'),
            tax_inclusive=True,
        )
        net_owed = sum(l.credit - l.debit
                       for l in _partner_lines(db, partner_customer.id).all())
        # net 100 - cost 30 = 70 → 25% = 17.5
        assert net_owed == Decimal('17.500')

    def test_inclusive_vat_mixed_treatments_only_standard_taxed(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        from services.sale_service import SaleService

        partner_customer.partner_scope = 'product'
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('100.00'),
        ))
        test_product.average_cost = Decimal('10')
        test_product.cost_price = Decimal('10')
        test_product.tax_treatment = 'zero'  # سطر صفري — لا يُستخرج منها ضريبة
        db.session.commit()

        SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('1'),
                'unit_price': Decimal('100'),
                'tax_treatment': 'zero',
            }],
            currency='AED',
            user_exchange_rate='1',
            tax_rate=Decimal('5'),
            tax_inclusive=True,
        )
        net_owed = sum(l.credit - l.debit
                       for l in _partner_lines(db, partner_customer.id).all())
        # لا ضريبة على السطر الصفري: 100 - 10 = 90 → 100% = 90
        assert net_owed == Decimal('90.000')


class TestPartnerProfitEdges:
    """تغطية الفروع الحدية — أي مسار يصلح في CI."""

    def test_to_date_accepts_iso_string_date_and_garbage(self):
        from datetime import date
        from services.partner_profit import _to_date

        assert _to_date(date(2026, 3, 1)) == date(2026, 3, 1)
        assert _to_date('2026-03-01') == date(2026, 3, 1)
        assert _to_date('garbage') is None
        assert _to_date(None) is None
        # صيغة ISO الأساسية (YYYYMMDD) تُقبل في Python 3.11+
        assert _to_date(20260301) == date(2026, 3, 1)
        assert _to_date('2026-99-99') is None

    def test_marker_window_parses_and_detects_malformed(self):
        from datetime import date
        from services.partner_profit import _marker_window

        assert _marker_window('partner-distribution:2026-03-01:2026-03-31:platform') == (
            date(2026, 3, 1), date(2026, 3, 31))
        assert _marker_window('partner-distribution:-:-:5') == (date.min, date.max)
        assert _marker_window('garbage') is None
        assert _marker_window('') is None

    def test_force_true_overrides_overlap_guard(self, db, app, gl_accounts):
        from datetime import date as _d

        def _revenue(day):
            from datetime import datetime
            from services.gl_service import GLService
            from services.account_resolution import AccountResolver, AccountRole
            GLService.post_entry(
                [{'account': AccountResolver.resolve(AccountRole.CASH),
                  'debit': Decimal('500'), 'description': 'd'},
                 {'account': AccountResolver.resolve(AccountRole.SALES_REVENUE),
                  'credit': Decimal('500'), 'description': 'd'}],
                description='إيراد', reference_type='Test',
                exchange_rate=Decimal('1'),
                entry_date=datetime(day.year, day.month, day.day))
            db.session.commit()

        _revenue(_d(2026, 3, 10))
        p = Customer(
            name='شريك مارس', name_ar='شريك مارس',
            customer_type='partner', partner_scope='company',
            partner_share=Decimal('50.000'), is_active=True,
        )
        db.session.add(p)
        db.session.commit()

        from services import partner_profit as pp
        first = pp.post_partner_distributions(_d(2026, 3, 1), _d(2026, 3, 31))
        assert first is not None
        # دخل أبريل لتغذية الربح في نافذة التداخل
        _revenue(_d(2026, 4, 15))
        # التكامل القسري يتجاوز حظر التقاطع
        forced = pp.post_partner_distributions(_d(2026, 3, 15), _d(2026, 4, 30),
                                               force=True)
        assert forced is not None

    def test_guard_ignores_foreign_tenant_markers(self, db, app, gl_accounts):
        from models import GLJournalEntry
        from services import partner_profit as pp
        p = Customer(
            name='شريك آخر', name_ar='شريك',
            customer_type='partner', partner_scope='company',
            partner_share=Decimal('25.000'), is_active=True,
        )
        db.session.add(p)
        db.session.commit()
        marker = 'partner-distribution:2026-03-01:2026-03-31:999'
        entry = GLJournalEntry(
            entry_number='JD-FOREIGN', entry_date=None, description='أجنبية',
            reference_type='PartnerDistribution', reference_id=None,
            entry_type='closing', currency='AED', exchange_rate=Decimal('1'),
            total_debit=Decimal('0'), total_credit=Decimal('0'),
            is_posted=True, is_reversed=False, notes=marker,
        )
        db.session.add(entry)
        db.session.commit()
        # طلب لجلسة تينانت مختلفة — مؤشر التينانت الأجنبي يُتجاهل
        pp._guard_against_overlapping_periods(date(2026, 3, 1), date(2026, 3, 31), 12345)
        # طلب على تينانت المنصة (None) — يتجاهل المؤشرات الرقمية
        pp._guard_against_overlapping_periods(date(2026, 3, 1), date(2026, 3, 31), None)

    def test_malformed_partner_distribution_marker_is_skipped(self, db, app, gl_accounts):
        from models import GLJournalEntry
        from services import partner_profit as pp
        entry = GLJournalEntry(
            entry_number='JD-BROKEN', entry_date=None, description='معطوبة',
            reference_type='PartnerDistribution', reference_id=None,
            entry_type='closing', currency='AED', exchange_rate=Decimal('1'),
            total_debit=Decimal('0'), total_credit=Decimal('0'),
            is_posted=True, is_reversed=False, notes='garbage-notes',
        )
        db.session.add(entry)
        db.session.commit()
        pp._guard_against_overlapping_periods(date(2026, 3, 1), date(2026, 3, 31), None)

    def test_compute_line_profit_without_sale_context(self):
        from services.partner_profit import compute_line_profit

        class _Line:
            quantity = Decimal('2')
            line_total = Decimal('100')
            cost_price = Decimal('30')
            sale = None

        assert compute_line_profit(_Line(), None) == Decimal('40.000')

        class _Empty:
            quantity = Decimal('0')
            line_total = Decimal('100')
            cost_price = Decimal('30')
            sale = None

        assert compute_line_profit(_Empty(), None) == Decimal('0.000')

    def test_sale_with_zero_profit_posts_no_partner_entry(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        from services.sale_service import SaleService

        partner_customer.partner_scope = 'product'
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('25.00'),
        ))
        # بيع بربح صفري — لا قيد شريك
        test_product.average_cost = Decimal('100')
        test_product.cost_price = Decimal('100')
        db.session.commit()

        SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('1'),
                'unit_price': Decimal('100'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
        )
        entries = [e for e in GLJournalEntry.query.all()
                   if 'Partner profit shares' in (e.description or '')]
        assert entries == []

    def test_draws_and_sales_window_filters(self, db, app, company_partner, gl_accounts):
        from datetime import date as _d
        from services.partner_profit import _draws_for_partner, _sales_to_partner

        draw = __import__('services.partner_profit', fromlist=['post_partner_draw']).post_partner_draw(
            company_partner.id, Decimal('100'))
        assert draw is not None
        assert _draws_for_partner(company_partner.id, _d(2000, 1, 1), _d(2099, 12, 31)) == Decimal('100.000')
        assert _draws_for_partner(company_partner.id, _d(2000, 1, 1), _d(2000, 12, 31)) == Decimal('0.000')
        assert _sales_to_partner(company_partner.id, _d(2000, 1, 1), _d(2000, 12, 31)) == Decimal('0.000')

    def test_post_partner_draw_validates_amount_and_partner(
            self, db, company_partner, gl_accounts):
        from services import partner_profit as pp

        with pytest.raises(ValueError):
            pp.post_partner_draw(company_partner.id, Decimal('0'))
        with pytest.raises(ValueError):
            pp.post_partner_draw(company_partner.id, Decimal('-5'))
        with pytest.raises(ValueError):
            pp.post_partner_draw(999999, Decimal('10'))

    def test_post_partner_draw_bank_credit_route(self, db, company_partner, gl_accounts):
        from services.account_resolution import AccountRole
        from services import partner_profit as pp

        entry = pp.post_partner_draw(company_partner.id, Decimal('77'),
                                     credit_account_role=AccountRole.BANK)
        assert entry is not None
        draw_lines = [l for l in entry.lines if l.description and 'مسحوبات' in l.description]
        assert draw_lines

    def test_post_partner_shares_for_return_without_sale_loads_it(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        from services.return_service import ReturnService
        from services.sale_service import SaleService
        from services import partner_profit as pp

        partner_customer.partner_scope = 'product'
        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('25.00'),
        ))
        test_product.average_cost = Decimal('30')
        test_product.cost_price = Decimal('30')
        db.session.commit()

        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('1'),
                'unit_price': Decimal('100'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
        )
        line = SaleLine.query.filter_by(sale_id=sale.id).first()
        ret = ReturnService.create_return(
            sale.id,
            [{'sale_line_id': line.id, 'quantity': Decimal('1'), 'condition': 'good'}],
            user_id=owner_user.id,
        )
        # نداء بلا sale — الدالة تتكفل بتحميله من المرتجع
        result = pp.post_partner_shares_for_return(ret, None)
        assert result is not None

    def test_main_preview_and_distribute_cli(self, db, app, company_partner, gl_accounts, capsys):
        from services import partner_profit as pp

        def _revenue():
            from services.gl_service import GLService
            from services.account_resolution import AccountResolver, AccountRole
            GLService.post_entry(
                [{'account': AccountResolver.resolve(AccountRole.CASH),
                  'debit': Decimal('600'), 'description': 'd'},
                 {'account': AccountResolver.resolve(AccountRole.SALES_REVENUE),
                  'credit': Decimal('600'), 'description': 'd'}],
                description='إيراد', reference_type='Test', exchange_rate=Decimal('1'))
            db.session.commit()

        _revenue()
        pp.main(['--preview'])
        out = capsys.readouterr().out
        assert 'شريك الشركة' in out
        pp.main(['--distribute'])
        out = capsys.readouterr().out
        assert 'Distributed' in out

    def test_post_partner_shares_for_return_missing_sale_lines(
            self, db, test_customer, test_product, gl_accounts):
        from services import partner_profit as pp
        from models import ProductReturn

        # مرتجع بلا أسطر — لا شيء للعكس
        product_return = ProductReturn(
            return_number='R-EDGE-1', sale_id=1, customer_id=test_customer.id,
            exchange_rate=Decimal('1'), currency='AED',
            total_amount=Decimal('0'), refund_amount=Decimal('0'),
            amount_base=Decimal('0'), status='approved',
        )
        db.session.add(product_return)
        db.session.flush()
        assert pp.post_partner_shares_for_return(product_return, None) is None

    def test_return_with_factor_for_unknown_sale_line_skipped(
            self, db, owner_user, test_customer, test_product, gl_accounts):
        from decimal import Decimal as D
        from services.partner_profit import compute_partner_shares

        sale_mock = type('S', (), {})()
        sale_mock.lines = []
        sale_mock.subtotal = D('0')

        assert compute_partner_shares(sale_mock) == {}


class TestPartnerDrawsViaAnyPath:
    """المسحوبات: تُحتسب آليًا بأي مسار موسوم بطرف الشريك — القيد اليدوي يشمل."""

    def test_manual_journal_tagged_3350_debit_counts_as_draw(
            self, db, app, company_partner, gl_accounts):
        from decimal import Decimal as D
        from services.gl_service import GLService
        from services import partner_profit as pp

        # إيراد 1000
        from services.account_resolution import AccountResolver, AccountRole
        GLService.post_entry(
            [{'account': AccountResolver.resolve(AccountRole.CASH),
              'debit': D('1000'), 'description': 'd'},
             {'account': AccountResolver.resolve(AccountRole.SALES_REVENUE),
              'credit': D('1000'), 'description': 'd'}],
            description='إيراد', reference_type='Test', exchange_rate=D('1'))

        # قيد يدوي بطرف الشريك على حسابه الجاري — يسجل كمسحوبات تلقائيًا
        entry = GLService.create_manual_entry(
            description='مسحوبات الشريك من المالك',
            lines=[
                {'account_code': '3350', 'debit': D('120'),
                 'description': 'مسحوبات', 'party_id': company_partner.id},
                {'account_code': '1110', 'credit': D('120'),
                 'description': 'صرف نقدي'},
            ],
            notes='قيد يدوي',
        )
        assert entry is not None
        assert pp._draws_for_partner(company_partner.id) == D('120.000')

        # المعاينة تُخصم منها المسحوبات تلقائيًا
        row = next(r for r in pp.preview_partner_distributions(None, None)
                   if r['partner_id'] == company_partner.id)
        assert row['draws_deducted'] == D('120.000')
        assert row['net_payout'] == D('130.000')

    def test_partner_share_entries_themselves_are_never_draws(
            self, db, owner_user, test_customer, test_product, partner_customer, gl_accounts):
        from services.sale_service import SaleService
        from services import partner_profit as pp
        from models import ProductPartner

        db.session.add(ProductPartner(
            product_id=test_product.id,
            partner_customer_id=partner_customer.id,
            percentage=Decimal('25.00'),
        ))
        test_product.average_cost = Decimal('30')
        test_product.cost_price = Decimal('30')
        db.session.commit()

        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('1'),
                'unit_price': Decimal('100'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
        )
        # عكسات الشريك من البيع لا تُحسب مسحوبات
        assert pp._draws_for_partner(partner_customer.id) == Decimal('0.000')

        SaleService.cancel_sale(sale)
        assert pp._draws_for_partner(partner_customer.id) == Decimal('0.000')

    def test_refund_to_partner_zeroed_sales_deduction(
            self, db, owner_user, test_product, company_partner, gl_accounts):
        from decimal import Decimal as D
        from services.sale_service import SaleService
        from services.return_service import ReturnService
        from services import partner_profit as pp
        from models import SaleLine

        company_partner.customer_type = 'partner'
        company_partner.partner_scope = 'company'
        db.session.commit()

        test_product.average_cost = Decimal('30')
        test_product.cost_price = Decimal('30')
        db.session.commit()

        sale = SaleService.create_sale(
            customer=company_partner,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('2'),
                'unit_price': Decimal('50'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
        )
        line = SaleLine.query.filter_by(sale_id=sale.id).first()
        # مرتجع كامل → balance_due = 0 → الخصم = صفر
        ReturnService.create_return(
            sale.id,
            [{'sale_line_id': line.id, 'quantity': Decimal('2'), 'condition': 'good'}],
            user_id=owner_user.id,
        )
        assert pp._sales_to_partner(company_partner.id) == D('0.000')

    def test_partial_return_prorates_sales_deduction(
            self, db, owner_user, test_product, company_partner, gl_accounts):
        from decimal import Decimal as D
        from services.sale_service import SaleService
        from services.return_service import ReturnService
        from services import partner_profit as pp
        from models import SaleLine

        company_partner.customer_type = 'partner'
        company_partner.partner_scope = 'company'
        db.session.commit()

        test_product.average_cost = Decimal('30')
        test_product.cost_price = Decimal('30')
        db.session.commit()

        sale = SaleService.create_sale(
            customer=company_partner,
            seller=owner_user,
            lines_data=[{
                'product': test_product,
                'quantity': Decimal('2'),
                'unit_price': Decimal('50'),
                'tax_treatment': 'exempt',
            }],
            currency='AED',
            user_exchange_rate='1',
        )
        line = SaleLine.query.filter_by(sale_id=sale.id).first()
        # مرتجع نصف → balance_due = 50
        ReturnService.create_return(
            sale.id,
            [{'sale_line_id': line.id, 'quantity': Decimal('1'), 'condition': 'good'}],
            user_id=owner_user.id,
        )
        remaining = pp._sales_to_partner(company_partner.id)
        assert remaining == D('50.000')
