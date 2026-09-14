def test_support_page_renders_arabic(client):
    resp = client.get('/auth/support')
    assert resp.status_code == 200
    assert 'تبرعك يساعدنا' in resp.get_data(as_text=True)


def test_support_page_renders_english(client):
    with client.session_transaction() as sess:
        sess['language'] = 'en'
    resp = client.get('/auth/support')
    assert resp.status_code == 200
    assert 'Complete Payment' in resp.get_data(as_text=True)


def test_language_switch_returns_to_referrer(client):
    resp = client.get('/language/set/en',
                      headers={'Referer': 'http://localhost/auth/support'})
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/auth/support')


def test_language_switch_invalid_lang_stays_safe(client):
    resp = client.get('/language/set/xx')
    assert resp.status_code == 302


def test_owner_dashboard_requires_login(client):
    resp = client.get('/owner/dashboard')
    assert resp.status_code == 302