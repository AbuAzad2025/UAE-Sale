from flask import Flask

def test_donation_model_repr():
    from models.donation import Donation
    d = Donation(amount_usd=50, payment_method='crypto', status='pending')
    assert 'crypto' in repr(d)
    assert d.is_pending is True
    d.status = 'completed'
    assert d.is_completed is True


def test_donation_static_methods_empty():
    from flask import Flask
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    from extensions import db
    db.init_app(app)
    from models.donation import Donation
    with app.app_context():
        db.create_all()
        assert Donation.get_total_donations() == 0.0
        assert Donation.get_donations_by_method() == []
        assert Donation.get_pending_count() == 0
        assert Donation.get_donations_count() == 0
