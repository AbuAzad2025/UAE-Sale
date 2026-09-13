def test_payment_form_class_importable():
    from forms.payment import ReceiptForm
    assert ReceiptForm is not None
