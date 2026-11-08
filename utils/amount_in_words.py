"""تحويل رقم إلى كلمات — لطباعة المبلغ الإجمالي على الفاتورة.

يدعم العربية والإنجليزية للأكثر شيوعًا من العملات (الخليج/الأردن/مصر/تركيا/أوروبا/أمريكا).
العربية تتبع الأسلوب التقليدي: "ثلاثة آلاف وخمسمائة ريال سعودي وخمسون هللة فقط".
الحد الأقصى المدعوم والموثّق: 999,999,999.999 — الفواتير لا تتجاوزه عمليًا.

ملاحظة قانونية صادقة: صيغة المبلغ بالكلمات تُسهّل الفوترة القانونية في دول مثل
السعودية/مصر لكنها لا تُغني عن أي متطلبات أخرى تفرضها سلطة الدولة.
"""
from decimal import Decimal, ROUND_HALF_UP

_ONES_AR = ['صفر', 'واحد', 'اثنان', 'ثلاثة', 'أربعة', 'خمسة', 'ستة', 'سبعة', 'ثمانية', 'تسعة']
_TEENS_AR = ['عشرة', 'أحد عشر', 'اثنا عشر', 'ثلاثة عشر', 'أربعة عشر', 'خمسة عشر',
             'ستة عشر', 'سبعة عشر', 'ثمانية عشر', 'تسعة عشر']
_TENS_AR = ['', '', 'عشرون', 'ثلاثون', 'أربعون', 'خمسون', 'ستون', 'سبعون', 'ثمانون', 'تسعون']
_HUNDRED_AR = 'مائة'
_HUNDREDS_MERGED_AR = {
    3: 'ثلاثمائة', 4: 'أربعمائة', 5: 'خمسمائة',
    6: 'ستمائة', 7: 'سبعمائة', 8: 'ثمانمائة', 9: 'تسعمائة',
}


def _three_ar(n):
    """كلمات الأرقام تحت الألف."""
    if n == 0:
        return ''
    parts = []
    hundreds = n // 100
    rem = n % 100
    if hundreds:
        if hundreds == 1:
            parts.append(_HUNDRED_AR)
        elif hundreds == 2:
            parts.append('مائتان')
        else:
            parts.append(_HUNDREDS_MERGED_AR.get(hundreds, f'{_ONES_AR[hundreds]} {_HUNDRED_AR}'))
    if rem < 10:
        if rem > 0:
            parts.append(_ONES_AR[rem])
    elif rem < 20:
        parts.append(_TEENS_AR[rem - 10])
    else:
        tens, ones = divmod(rem, 10)
        if ones:
            parts.append(f'{_ONES_AR[ones]} و{_TENS_AR[tens]}')
        else:
            parts.append(_TENS_AR[tens])
    return ' و'.join(parts)


def number_words_ar(n):
    n = int(n)
    if n == 0:
        return 'صفر'
    parts = []
    for divider, singular, dual, plural in (
        (1_000_000_000, 'مليار', 'مليارين', 'مليارات'),
        (1_000_000, 'مليون', 'مليونين', 'ملايين'),
        (1_000, 'ألف', 'ألفين', 'آلاف'),
    ):
        count, n = divmod(n, divider)
        if count:
            if count == 1:
                parts.append(singular)
            elif count == 2:
                parts.append(dual)
            elif 3 <= count <= 10:
                parts.append(f'{_ONES_AR[count]} {plural}')
            else:
                parts.append(f'{_three_ar(count)} {singular}')
    if n:
        parts.append(_three_ar(n))
    return ' و'.join(parts)


_ONES_EN = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
_TENS_EN = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _three_en(n):
    parts = []
    if n >= 100:
        parts.append(f'{_ONES_EN[n // 100]} Hundred')
        n %= 100
    if n >= 20:
        t = _TENS_EN[n // 10]
        o = _ONES_EN[n % 10] if n % 10 else ''
        parts.append(f'{t} {o}'.strip())
    elif n > 0:
        parts.append(_ONES_EN[n])
    return ' '.join(parts)


def number_words_en(n):
    n = int(n)
    if n == 0:
        return 'Zero'
    parts = []
    for divider, name in ((1_000_000_000, 'Billion'), (1_000_000, 'Million'), (1_000, 'Thousand')):
        count, n = divmod(n, divider)
        if count:
            parts.append(f'{number_words_en(count)} {name}')
    if n:
        parts.append(_three_en(n))
    return ' '.join(parts)


_CURRENCY_NAMES = {
    'AED': ('درهم إماراتي', 'فلس', 'UAE Dirham', 'Fils'),
    'SAR': ('ريال سعودي', 'هللة', 'Saudi Riyal', 'Halala'),
    'ILS': ('شيكل جديد', 'أغورة', 'New Sheqel', 'Agora'),
    'USD': ('دولار أمريكي', 'سنت', 'US Dollar', 'Cent'),
    'EUR': ('يورو', 'سنت', 'Euro', 'Cent'),
    'KWD': ('دينار كويتي', 'فلس', 'Kuwaiti Dinar', 'Fils'),
    'QAR': ('ريال قطري', 'درهم', 'Qatari Riyal', 'Dirham'),
    'BHD': ('دينار بحريني', 'فلس', 'Bahraini Dinar', 'Fils'),
    'OMR': ('ريال عماني', 'بيسة', 'Omani Rial', 'Baisa'),
    'JOD': ('دينار أردني', 'قرش', 'Jordanian Dinar', 'Piastre'),
    'EGP': ('جنيه مصري', 'قرش', 'Egyptian Pound', 'Piastre'),
    'TRY': ('ليرة تركية', 'قرش', 'Turkish Lira', 'Kurus'),
    'GBP': ('جنيه إسترليني', 'بنس', 'British Pound', 'Penny'),
}


def amount_in_words(amount, currency_code='AED', lang='ar'):
    """الجملة الكاملة للمبلغ — مثال: 'ثلاثة آلاف وخمسمائة ريال سعودي وخمسون هللة فقط'."""
    try:
        value = Decimal(str(amount or 0))
    except Exception:
        value = Decimal('0')
    value = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    units = _CURRENCY_NAMES.get((currency_code or '').upper())
    whole = int(value)
    fraction = int((value - Decimal(whole)) * Decimal('100'))

    if lang == 'en':
        unit = (units[2] if units else (currency_code or 'Currency'))
        sub = (units[3] if units else '')
        words = f'{number_words_en(whole)} {unit}'
        if fraction:
            words += f' and {number_words_en(fraction)} {sub}'
        return f'{words} only'

    unit = (units[0] if units else (currency_code or 'عملة'))
    sub = (units[1] if units else '')
    words = f'{number_words_ar(whole)} {unit}'
    if fraction:
        words += f' و{number_words_ar(fraction)} {sub}'
    return f'{words} فقط'
