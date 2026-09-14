def test_card_payment_repr():
    from models.card_payment import CardPayment
    cp = CardPayment(customer_name='X', amount=10, status='pending', card_type='Visa', card_last_4='4321')
    assert '****4321' in repr(cp)
    assert cp.get_card_display() == 'Visa ****4321'


def test_token_hash_irreversible():
    from models.card_payment import CardPayment
    h1 = CardPayment._token_hash('4111111111111111')
    h2 = CardPayment._token_hash('4111111111111111')
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex length


def test_looks_like_legacy():
    from models.card_payment import CardPayment
    import base64, json
    cp = CardPayment(customer_name='X', amount=1, status='pending')
    cp.encrypted_data = base64.b64encode(json.dumps({'card_number':'4111','cvv':'123'}).encode()).decode()
    assert cp._looks_like_legacy_payload() is True


def _set_key(app, monkeypatch):
    monkeypatch.setitem(app.config, 'CARD_ENCRYPTION_KEY', 'test-card-key-123')


def test_encrypt_decrypt_roundtrip_discards_cvv(app, db, monkeypatch):
    from models.card_payment import CardPayment
    _set_key(app, monkeypatch)
    cp = CardPayment(customer_name='C', transaction_type='donation', amount=200, status='pending')
    assert cp.encrypt_card_data('4111 1111 1111 1111', '123', '12/30') is True
    assert cp.card_last_4 == '1111'
    assert cp.card_type == 'Visa'
    assert cp.card_bin == '411111'
    data = cp.decrypt_card_data()
    assert data is not None
    assert set(data.keys()) == {'card_number', 'expiry', 'display'}
    assert data['card_number'] == '****1111'
    assert data['expiry'] == '12/30'


def test_decrypt_rejects_legacy_payload(app, db, monkeypatch):
    import base64, json
    from models.card_payment import CardPayment, LEGACY_PAYLOAD_MESSAGE
    _set_key(app, monkeypatch)
    cp = CardPayment(customer_name='C', transaction_type='donation', amount=10, status='pending')
    cp.encrypted_data = base64.b64encode(
        json.dumps({'card_number': '4111111111111111', 'cvv': '123'}).encode()).decode()
    try:
        cp.decrypt_card_data()
        raise AssertionError('legacy payload must be rejected')
    except ValueError as e:
        assert str(e) == LEGACY_PAYLOAD_MESSAGE


def test_totals_and_stats_with_real_rows(db):
    from extensions import db as _db
    from models.card_payment import CardPayment
    rows = [
        CardPayment(customer_name='A', transaction_type='donation', amount=100,
                    status='completed', card_type='Visa', card_last_4='1111'),
        CardPayment(customer_name='B', transaction_type='purchase', amount=200,
                    status='completed', card_type='Mastercard', card_last_4='2222'),
        CardPayment(customer_name='C', transaction_type='donation', amount=50,
                    status='pending', card_type='Visa', card_last_4='3333'),
    ]
    _db.session.add_all(rows)
    _db.session.commit()
    assert CardPayment.get_total_card_payments() == 300.0
    stats = {s['type']: s for s in CardPayment.get_card_stats()}
    assert stats['Visa'] == {'type': 'Visa', 'count': 1, 'total': 100.0}
    assert stats['Mastercard'] == {'type': 'Mastercard', 'count': 1, 'total': 200.0}


def test_decrypt_without_data_returns_none(db):
    from models.card_payment import CardPayment
    cp = CardPayment(customer_name='C', transaction_type='donation', amount=10, status='pending')
    assert cp.decrypt_card_data() is None


def test_encrypt_fails_without_key(app, db, monkeypatch):
    from models.card_payment import CardPayment
    monkeypatch.delitem(app.config, 'CARD_ENCRYPTION_KEY', raising=False)
    cp = CardPayment(customer_name='C', transaction_type='donation', amount=10, status='pending')
    assert cp.encrypt_card_data('4111111111111111', '123', '12/30') is False


def test_decrypt_corrupt_non_legacy_returns_none(app, db, monkeypatch):
    from models.card_payment import CardPayment
    _set_key(app, monkeypatch)
    cp = CardPayment(customer_name='C', transaction_type='donation', amount=10, status='pending')
    cp.encrypted_data = 'not-valid-payload-at-all'
    assert cp.decrypt_card_data() is None


def test_to_dict_basic_shape(db):
    from extensions import db as _db
    from models.card_payment import CardPayment
    cp = CardPayment(customer_name='S', customer_email='s@x.com', transaction_type='purchase',
                     package='basic', amount=75, status='completed',
                     card_type='Visa', card_last_4='4444')
    _db.session.add(cp)
    _db.session.commit()
    data = CardPayment.query.first().to_dict()
    assert data['customer_name'] == 'S'
    assert data['amount'] == 75.0
    assert data['card_display'] == 'Visa ****4444'
    assert data['status'] == 'completed'
    assert 'decrypted' not in data


def test_to_dict_owner_can_include_decrypted(app, db, monkeypatch):
    from extensions import db as _db
    from models.card_payment import CardPayment
    _set_key(app, monkeypatch)
    monkeypatch.setitem(app.config, 'ALLOW_CARD_DECRYPTION', True)
    cp = CardPayment(customer_name='S', transaction_type='donation', amount=75,
                     status='completed')
    assert cp.encrypt_card_data('4111111111111111', '123', '01/28') is True
    _db.session.add(cp)
    _db.session.commit()
    data = CardPayment.query.first().to_dict(include_encrypted=True)
    assert data['decrypted']['card_number'] == '****1111'
    assert data['decrypted']['expiry'] == '01/28'