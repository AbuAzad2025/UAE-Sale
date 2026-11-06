"""Guide endpoint tests — نطاق آمن"""
import pytest


def test_guide_endpoint_requires_login(client):
    r = client.get("/ai/guide")
    assert r.status_code in (401, 302, 403)
