from flask import Flask
from flask_testing import TestCase

def create_app():
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key-not-for-production'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    from routes.api_analytics import api_analytics_bp
    from routes import graphql  # just import to register blueprints
    app.register_blueprint(api_analytics_bp)
    return app

class AnalyticsAPITests(TestCase):
    def create_app(self):
        return create_app()

    def test_health_route_liveness(self):
        # Focus on the analytics endpoint behavior rather than DB state
        resp = self.client.get('/api/analytics/revenue-trend')
        # Authentication required will redirect or 302; we just verify endpoint exists
        self.assertIn(resp.status_code, [200, 302, 401, 403])
