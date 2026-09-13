from flask import Flask

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
