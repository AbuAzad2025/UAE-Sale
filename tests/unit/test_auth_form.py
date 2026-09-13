from flask import Flask

def test_login_form_valid():
    from forms.auth import LoginForm
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_request_context():
        form = LoginForm(username='adminuser', password='secret')
        assert form.validate() is True


def test_login_form_short_username():
    from forms.auth import LoginForm
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_request_context():
        form = LoginForm(username='ab', password='secret')
        assert form.validate() is False
        assert 'username' in form.errors
