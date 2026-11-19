"""page_title must render once; the breadcrumb gets plain text only.

base.html previously injected the whole page_title block into both the header
<h1> and the breadcrumb, duplicating titles and buttons on 50+ pages.
"""
import pytest


@pytest.mark.parametrize("path", ["/customers/", "/products/"])
def test_header_rendered_once_and_breadcrumb_is_plain(client, login_as, path):
    login_as("manager")
    resp = client.get(path)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # One page-title host and a single heading/button inside it.
    assert body.count('class="page-title-host"') == 1
    host = body.split('class="page-title-host"', 1)[1].split("</div>", 1)[0]
    assert host.count("<h1") <= 1

    # Breadcrumb is text, not a second copy of the toolbar (no button labels).
    crumb = body.split('breadcrumb-item active', 1)[1].split("</li>", 1)[0]
    assert "btn" not in crumb
    assert "<h1" not in crumb
    assert "<a " not in crumb


def test_page_title_text_filter():
    from app import _page_title_text

    html = ('<div class="d-flex"><h1 class="mb-0"><i class="fas fa-users"></i>'
            'إدارة الزبائن</h1><a class="btn" href="#">زبون جديد</a></div>')
    assert str(_page_title_text(html)) == "إدارة الزبائن"
    assert str(_page_title_text("كشف حساب المورد")) == "كشف حساب المورد"
