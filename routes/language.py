"""
Language Routes - تبديل اللغة
"""
from flask import Blueprint, request, redirect, url_for, session, flash

language_bp = Blueprint('language', __name__, url_prefix='/language')


@language_bp.route('/set/<lang>')
def set_language(lang):
    """تغيير اللغة"""
    if lang in ['ar', 'en']:
        session['language'] = lang
        flash(f'تم تغيير اللغة إلى {"العربية" if lang == "ar" else "English"}', 'success')

    # منع open redirect: لا نثق بـ Referer (قد يشير لنطاق خارجي)
    next_url = request.args.get('next', '')
    if next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(url_for('main.dashboard'))
