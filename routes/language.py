"""
Language Routes - تبديل اللغة
"""
from flask import Blueprint, request, redirect, url_for, session, flash
from urllib.parse import urlparse

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
    # Fallback: return to the page the user came from (same host only) so
    # switching language on a public page doesn't dump visitors at login.
    ref = request.referrer or ''
    try:
        parts = urlparse(ref)
        # Compare hostnames without ports: browsers send absolute referrers
        # (e.g. localhost:8001) while request.host may omit the port.
        ref_host = (parts.hostname or '').lower()
        own_host = (request.host or '').split(':')[0].lower()
        if (parts.path.startswith('/') and not parts.path.startswith('//')
                and ref_host in ('', own_host)):
            ref_target = parts.path
            if parts.query:
                ref_target += '?' + parts.query
            return redirect(ref_target)
    except Exception:
        pass
    return redirect(url_for('main.dashboard'))
