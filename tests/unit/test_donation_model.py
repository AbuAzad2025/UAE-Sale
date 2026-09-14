from datetime import datetime


def test_donation_model_repr():
    from models.donation import Donation
    d = Donation(amount_usd=50, payment_method='crypto', status='pending')
    assert 'crypto' in repr(d)
    assert d.is_pending is True
    d.status = 'completed'
    assert d.is_completed is True


def test_donation_static_methods_empty(db):
    from models.donation import Donation
    assert Donation.get_total_donations() == 0.0
    assert Donation.get_donations_by_method() == []
    assert Donation.get_pending_count() == 0
    assert Donation.get_donations_count() == 0


def _seed_donations():
    from models.donation import Donation
    from extensions import db as _db
    rows = [
        Donation(amount_usd=50, payment_method='crypto', crypto_type='btc',
                 status='completed', donor_name='A',
                 completed_at=datetime(2026, 1, 1)),
        Donation(amount_usd=100, payment_method='bank',
                 status='completed', donor_name='B',
                 completed_at=datetime(2026, 1, 2)),
        Donation(amount_usd=20, payment_method='paypal', status='pending'),
        Donation(amount_usd=5, payment_method='crypto', status='failed'),
    ]
    _db.session.add_all(rows)
    _db.session.commit()
    return rows


def test_donation_aggregates_with_real_rows(db):
    from models.donation import Donation
    _seed_donations()
    assert Donation.get_total_donations() == 150.0
    assert Donation.get_donations_count() == 2
    assert Donation.get_pending_count() == 1
    by_method = {r['method']: r for r in Donation.get_donations_by_method()}
    assert by_method['crypto'] == {'method': 'crypto', 'count': 1, 'total': 50.0}
    assert by_method['bank'] == {'method': 'bank', 'count': 1, 'total': 100.0}


def test_donation_recent_orders_by_completed_at(db):
    from models.donation import Donation
    _seed_donations()
    recent = Donation.get_recent_donations(limit=10)
    assert [d.donor_name for d in recent] == ['B', 'A']


def test_donation_to_dict(db):
    from extensions import db as _db
    from models.donation import Donation
    d = Donation(amount_usd=50, amount_crypto=None, payment_method='crypto',
                 crypto_type='btc', status='pending', donor_name='A')
    _db.session.add(d)
    _db.session.commit()
    data = Donation.query.first().to_dict()
    assert data['amount_usd'] == 50.0
    assert data['amount_crypto'] is None
    assert data['payment_method'] == 'crypto'
    assert data['status'] == 'pending'
    assert data['created_at'] is not None
    assert data['confirmed_at'] is None