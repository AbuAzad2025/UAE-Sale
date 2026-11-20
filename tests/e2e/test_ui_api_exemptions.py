"""UI support endpoints under /api must not require the paid API package."""
from sqlalchemy import text


def test_ui_support_endpoints_work_without_api_package(client, login_as, app, db):
    mgr = login_as("manager")
    with app.app_context():
        db.session.execute(
            text("UPDATE tenants SET enable_api=0 WHERE id=:i"), {"i": mgr.tenant_id})
        db.session.commit()

    for path in ("/api/payment-fields/cash", "/api/search?q=test&type=customers"):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code,
                                         resp.get_data(as_text=True)[:200])

    with app.app_context():
        db.session.execute(
            text("UPDATE tenants SET enable_api=1 WHERE id=:i"), {"i": mgr.tenant_id})
        db.session.commit()
