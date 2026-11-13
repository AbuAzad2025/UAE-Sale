"""
Public Routes - Landing Page, Pricing, User Guide, SEO
"""

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    Response,
    request,
    session,
)
from flask_login import current_user

public_bp = Blueprint("public", __name__)


@public_bp.route("/welcome")
def landing():
    """Landing Page — for guests it renders the marketing page; for
    authenticated users it redirects to the role-appropriate dashboard
    (owner/super_admin -> /owner/dashboard, others -> /dashboard)."""
    if current_user.is_authenticated:
        _slug = getattr(getattr(current_user, "role", None), "slug", None)
        if (
            getattr(current_user, "is_owner", False)
            or current_user.is_super_admin()
            or _slug == "developer"
        ):
            return redirect(url_for("owner.dashboard"))
        return redirect(url_for("main.dashboard"))
    if session.get("language") == "en":
        return render_template("public/landing_en.html")
    return render_template("public/landing.html")


@public_bp.route("/pricing")
def pricing():
    """صفحة الأسعار والعروض — تُبنى ديناميكيًا من جدول الخطط."""
    from flask import session

    try:
        from models import SubscriptionPlan

        plans = (
            SubscriptionPlan.query.filter_by(is_public=True, is_active=True)
            .order_by(SubscriptionPlan.sort_order, SubscriptionPlan.id)
            .all()
        )
    except Exception:
        plans = []
    if session.get("language") == "en":
        return render_template("public/pricing_en.html", plans=plans)
    return render_template("public/pricing.html", plans=plans)


@public_bp.route("/features")
def features():
    """صفحة المميزات"""
    if session.get("language") == "en":
        return render_template("public/features_en.html")
    return render_template("public/features.html")


@public_bp.route("/user-guide")
def user_guide():
    """دليل المستخدم"""
    from flask import session

    lang = session.get("language", "ar")

    if lang == "en":
        return render_template("public/user_guide_en.html")
    else:
        return render_template("public/user_guide.html")


@public_bp.route("/contact")
def contact():
    """اتصل بنا"""
    if session.get("language") == "en":
        return render_template("public/contact_en.html")
    return render_template("public/contact.html")


@public_bp.route("/terms")
def terms():
    """شروط الخدمة"""
    if session.get("language") == "en":
        return render_template("public/terms_en.html")
    return render_template("public/terms.html")


@public_bp.route("/privacy")
def privacy():
    """سياسة الخصوصية"""
    if session.get("language") == "en":
        return render_template("public/privacy_en.html")
    return render_template("public/privacy.html")


@public_bp.route("/sla")
def sla():
    """التزامات مستوى الخدمة (SLA)"""
    if session.get("language") == "en":
        return render_template("public/sla_en.html")
    return render_template("public/sla.html")


@public_bp.route("/contract")
def contract():
    """عقد الاشتراك (نموذج يُرسَل للعميل ويُوقَّع من الطرفين)"""
    try:
        from models import SubscriptionPlan

        plans = (
            SubscriptionPlan.query.filter_by(is_public=True, is_active=True)
            .order_by(SubscriptionPlan.sort_order, SubscriptionPlan.id)
            .all()
        )
    except Exception:
        plans = []
    if session.get("language") == "en":
        return render_template("public/contract_en.html", plans=plans)
    return render_template("public/contract.html", plans=plans)


@public_bp.route("/demo")
def demo():
    """طلب نسخة تجريبية"""
    if session.get("language") == "en":
        return render_template("public/demo_en.html")
    return render_template("public/demo.html")


@public_bp.route("/sitemap.xml")
def sitemap():
    """
    خريطة الموقع الديناميكية لمحركات البحث
    Dynamic Sitemap for Search Engines (Google, Bing, etc.)
    """
    from models import Product

    base_url = request.url_root.rstrip("/")

    static_pages = [
        {
            "loc": f"{base_url}/",
            "priority": "1.0",
            "changefreq": "daily",
            "keywords": "نظام إدارة مستودعات، برنامج محاسبة الإمارات",
        },
        {
            "loc": f"{base_url}/pricing",
            "priority": "0.95",
            "changefreq": "weekly",
            "keywords": "أسعار برنامج المستودعات، باقات محاسبة",
        },
        {
            "loc": f"{base_url}/features",
            "priority": "0.95",
            "changefreq": "weekly",
            "keywords": "مميزات نظام المستودعات، خصائص البرنامج",
        },
        {
            "loc": f"{base_url}/demo",
            "priority": "0.90",
            "changefreq": "weekly",
            "keywords": "تجربة مجانية، عرض توضيحي",
        },
        {
            "loc": f"{base_url}/sla",
            "priority": "0.85",
            "changefreq": "monthly",
            "keywords": "التزامات مستوى الخدمة، SLA",
        },
        {
            "loc": f"{base_url}/contract",
            "priority": "0.85",
            "changefreq": "monthly",
            "keywords": "عقد الاشتراك، نموذج",
        },
        {
            "loc": f"{base_url}/terms",
            "priority": "0.80",
            "changefreq": "monthly",
            "keywords": "شروط الخدمة",
        },
        {
            "loc": f"{base_url}/privacy",
            "priority": "0.80",
            "changefreq": "monthly",
            "keywords": "سياسة الخصوصية",
        },
        {
            "loc": f"{base_url}/contact",
            "priority": "0.90",
            "changefreq": "monthly",
            "keywords": "اتصل بنا، دبي، الإمارات",
        },
        {
            "loc": f"{base_url}/user-guide",
            "priority": "0.85",
            "changefreq": "monthly",
            "keywords": "دليل المستخدم، شرح البرنامج",
        },
        {
            "loc": f"{base_url}/auth/login",
            "priority": "0.80",
            "changefreq": "monthly",
            "keywords": "تسجيل دخول",
        },
    ]

    try:
        products = (
            Product.query.filter_by(is_active=True)
            .order_by(Product.updated_at.desc())
            .limit(100)
            .all()
        )

        for product in products:
            static_pages.append(
                {
                    "loc": f"{base_url}/products/{product.id}",
                    "priority": "0.7",
                    "changefreq": "weekly",
                    "lastmod": product.updated_at.strftime("%Y-%m-%d")
                    if product.updated_at
                    else None,
                }
            )
    except Exception:
        pass

    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for page in static_pages:
        xml_content += "  <url>\n"
        xml_content += f"    <loc>{page['loc']}</loc>\n"
        xml_content += f"    <priority>{page['priority']}</priority>\n"
        xml_content += f"    <changefreq>{page['changefreq']}</changefreq>\n"
        if page.get("lastmod"):
            xml_content += f"    <lastmod>{page['lastmod']}</lastmod>\n"
        xml_content += "  </url>\n"

    xml_content += "</urlset>"

    return Response(xml_content, mimetype="application/xml")


@public_bp.route("/robots.txt")
def robots():
    """
    ملف Robots.txt لتوجيه محركات البحث
    Robots.txt for Search Engine Crawlers
    """
    base_url = request.url_root.rstrip("/")

    robots_content = """# شركة أزاد للأنظمة الذكية

User-agent: *
Allow: /
Allow: /pricing
Allow: /features
Allow: /user-guide
Allow: /contact
Allow: /demo
Allow: /static/

Disallow: /owner/
Disallow: /dashboard
Disallow: /auth/
Disallow: /api/
Disallow: /admin/

Disallow: /instance/
Disallow: /logs/
Disallow: /migrations/

Sitemap: {base_url}/sitemap.xml

Crawl-delay: 1
"""

    return Response(
        robots_content.replace("{base_url}", base_url), mimetype="text/plain"
    )
