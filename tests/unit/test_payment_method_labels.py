"""Payment methods must never appear as raw codes in either UI language."""
import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')

from app import create_app


def _methods(lang):
    app = create_app()
    with app.test_request_context('/'):
        from flask import session
        from app import _status_label
        session['language'] = lang
        return [_status_label(m) for m in ('cash','card','bank_transfer','cheque','e_wallet')]


def test_payment_methods_ar():
    vals = _methods('ar')
    assert vals == ['نقدي','بطاقة','تحويل بنكي','شيك','محفظة إلكترونية'], vals


def test_payment_methods_en():
    vals = _methods('en')
    assert vals == ['Cash','Card','Bank Transfer','Cheque','E-Wallet'], vals
