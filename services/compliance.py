"""Snapshots per-country technical readiness — honest, not aspirational.

يقدم لوحة "لقطة الامتثال" — أي ماذا يدعمه التطبيق حاليًا من متطلبات كل دولة وما
لا يتوافق معه — بشكل صريح بلا تزيين. لايُدَّعى التكامل الفعلي مع أي سلطة ضريبية
حكومية؛ تظهر كل ميزة بحالة: مدعوم / غير مدعوم / يحتاج محاسبًا معتمدًا بالتشغيل.
"""
from decimal import Decimal


_COUNTRY_REQUIREMENTS = {
    'AE': {
        'name': 'الإمارات العربية المتحدة',
        'authority': 'Federal Tax Authority (FTA)',
        'mandatory_invoice_features': [
            {'name': 'TRN على كل فاتورة، إجمالي فرعي وصافي', 'status': 'supported',
             'detail': 'الرقم الضريبي والاسم والعنوان محفوظان على التينانت ويُطبعان تلقائيًا من utils/invoice_header.py.'},
            {'name': 'نسبة VAT الشركة ومنسوب شامل/إضافي وسلطةُ المعاملة', 'status': 'supported',
             'detail': 'VAT per line (standard / zero-rated / exempt) + inclusive mode + per-line snapshot — sale_tax_calculation.py.'},
            {'name': 'تقرير VAT للمدخلات والمخرجات والإشعار الدائن', 'status': 'supported',
             'detail': '/reports/vat-report مع تصدير xlsx/pdf/csv.'},
            {'name': 'التكامل الإلزامي مع FTA للإقرارات والربط الحي', 'status': 'not_supported',
             'detail': 'مطلوب ربط مع SLA/API الخاص بـ FTA — غير منفذ ولا يُمكن بدون عقد مع سلطة الدولة.'},
            {'name': 'توقيع الفاتورة الإلكترونية بالشهادة المعتمدة', 'status': 'not_supported',
             'detail': 'يتطلب شهادة رقمية لكل شركة تقدم من السلطة — لا يملكها التطبيق.'},
        ],
    },
    'SA': {
        'name': 'المملكة العربية السعودية',
        'authority': 'الهيئة العامة للزكاة والدخل / ZATCA',
        'mandatory_invoice_features': [
            {'name': 'المرحلة 1 (فاتورة) — QR على كل فاتورة', 'status': 'partial',
             'detail': 'يمكن إضافة صورة QR ببيانات TRN من خلال owner→tenant profile؛ أما التوقيع المعتمد فغير مدعوم.'},
            {'name': 'المرحلة 2 (التكامل والربط مع ZATCA) — الفاتورة الإلكترونية المفوترة', 'status': 'not_supported',
             'detail': 'تطلب شهادة CSID من ZATCA + SHA256 + UUID/Timestamp من نقطة دخولك للوصل إليهم — غير منفذ.'},
            {'name': 'VAT 15% وإدخال الفواتير الضريبية', 'status': 'supported',
             'detail': 'يدير التطبيق الضريبة بأي نسبة حسب country_code وtax_rulesets.vat_rate.'},
            {'name': 'رمز كل بند ضريبي (S/Z/E) لكل بند', 'status': 'supported',
             'detail': 'tax_treatment على كل بند + snapshot على الفاتورة — غير مرئي لمركز خدمات المبيعات لدى RT.'},
            {'name': 'النشر عبر SFTP/نقطة اتصال ZATCA', 'status': 'not_supported',
             'detail': 'تكامل RTU/TLD/الربط مع ZATCA — غير منفذ ويحتاج دخول بيئة المنصة.'},
        ],
    },
    'EG': {
        'name': 'جمهورية مصر العربية',
        'authority': 'مصلحة الضرائب المصرية / ETA',
        'mandatory_invoice_features': [
            {'name': 'ETA — الفاتورة الإلكترونية (التصدير/الاستيراد فقط Cathode)', 'status': 'not_supported',
             'detail': 'requires ETA credentials + XML 414 Format — غير مدعوم رسميًا.'},
            {'name': 'TRN + VAT 14% + <ksattc>', 'status': 'partial',
             'detail': 'العرض في الإدخال يدير النسبة لكن لا يتوافق XML مع Schema ETA.'},
        ],
    },
    'JO': {
        'name': 'المملكة الأردنية الهاشمية',
        'authority': 'دائرة ضريبة الدخل والمبيعات',
        'mandatory_invoice_features': [
            {'name': 'TRN وVAT 16%', 'status': 'supported',
             'detail': 'النسبة قابلة للتعديل من لوحة المالك؛ لا توجد شهادة امتثال رسمية من داخل التطبيق.'},
            {'name': 'Report to authority', 'status': 'not_supported',
             'detail': 'لا يوجد e-filing — الإقرار نمط يدوي للمختص.'},
        ],
    },
    'TR': {
        'name': 'تركيا',
        'authority': 'Gelir İdaresi Başkanlığı / GİB',
        'mandatory_invoice_features': [
            {'name': 'e-Fatura (XML + XSD + certificate)', 'status': 'not_supported',
             'detail': 'تتطلب شهادة kvalifiye مع GİB + تعريف خط كميات — غير منفذ.'},
            {'name': 'KDV 20% (VAT تركيا)', 'status': 'supported',
             'detail': 'النسبة قابلة للتعديل من لوحة المالك فقط.'},
        ],
    },
    'GB': {
        'name': 'المملكة المتحدة',
        'authority': 'HM Revenue and Customs / HMRC',
        'mandatory_invoice_features': [
            {'name': 'Making Tax Digital — MTD VAT', 'status': 'not_supported',
             'detail': 'ربط API مع HMRC مباشرة بشهادة OAuth — غير منفذ.'},
            {'name': 'VAT 20% (MTD غير مُنفذ)', 'status': 'supported',
             'detail': 'النسبة قابلة للتعديل؛ ربط MTD مع HMRC غير مدعوم.'},
        ],
    },
    'DE': {
        'name': 'ألمانيا',
        'authority': 'Bundeszentralamt für Steuern / BZSt',
        'mandatory_invoice_features': [
            {'name': 'XRechnung', 'status': 'not_supported',
             'detail': 'XRechnung/ ZUGFeRD أو Factur-X فقط — غير منفذ.'},
            {'name': 'VAT 19%', 'status': 'supported',
             'detail': 'النسبة قابلة للتعديل.'},
        ],
    },
    'OM': {
        'name': 'سلطنة عمان',
        'authority': 'Oman Tax Authority',
        'mandatory_invoice_features': [
            {'name': 'VAT 5%', 'status': 'supported',
             'detail': 'النسبة قابلة للتعديل.'},
            {'name': 'تكامل سلطة ضريبة عُمان / e-filing', 'status': 'not_supported',
             'detail': 'لا يوجد e-filing مدعوم.'},
        ],
    },
    'BH': {
        'name': 'مملكة البحرين',
        'authority': 'NBR هيأة الضرائب',
        'mandatory_invoice_features': [
            {'name': 'VAT 10% + فاتورة ضريبية', 'status': 'supported',
             'detail': 'النسبة قابلة للتعديل.'},
            {'name': 'NBR integration', 'status': 'not_supported',
             'detail': 'لا يوجد e-filing مدعوم.'},
        ],
    },
    'KW': {
        'name': 'دولة الكويت',
        'authority': 'لم تُفعّل',
        'mandatory_invoice_features': [
            {'name': 'VAT غير مُفعّل في الكويت', 'status': 'supported',
             'detail': 'افتراضيًا النسبة صفر => VAT معطل تلقائيًا (country_code=KW).'},
        ],
    },
    'QA': {
        'name': 'دولة قطر',
        'authority': 'لم تُفعّل',
        'mandatory_invoice_features': [
            {'name': 'VAT غير مُفعّل في قطر', 'status': 'supported',
             'detail': 'default_tax_rate=0 => VAT disabled automatically.'},
        ],
    },
}


def country_compliance_snapshot():
    """يعيد قائمة كل دولة ومتطلباتها وما يدعمه التطبيق بصدق.

    المصطلحات:
      supported      — مدعوم تقنياً الآن.
      partial        — مدعوم جزئياً (يحتاج خطوة إضافية).
      not_supported  — غير مدعوم ويتطلب عقدًا + شهادة من سلطة الدولة.
    """
    items = []
    for code, meta in _COUNTRY_REQUIREMENTS.items():
        features = meta['mandatory_invoice_features']
        status_counts = {}
        for f in features:
            status_counts[f['status']] = status_counts.get(f['status'], 0) + 1
        items.append({
            'country_code': code,
            'name': meta['name'],
            'authority': meta['authority'],
            'features': features,
            'supported': status_counts.get('supported', 0),
            'partial': status_counts.get('partial', 0),
            'not_supported': status_counts.get('not_supported', 0),
            'is_ready_for_legal_approval': status_counts.get('not_supported', 0) == 0,
        })
    return items


def summary_of_supported_features():
    """ملخّص للمنشأة بدون مفاهيم البروتوكول: ما يدعمه التطبيق فعلياً الآن."""
    return {
        'tax_rule_management': True,
        'per_line_tax_treatments': True,
        'tenant_invoice_identity': True,
        'inclusive_exclusive_vat': True,
        'zero_rated_and_exempt_treatments': True,
        'per_country_configuration_editable': True,
        'tenant_specific_rulesets_optional': True,  # via tax_rulesets.tenant_id
        'printing_compliance': False,
        'e_invoice_authority_integration': False,
        'signed_invoice_certificate': False,
        'automated_returns_filing': False,
        'multi_jurisdiction_simultaneous_support': True,
    }
