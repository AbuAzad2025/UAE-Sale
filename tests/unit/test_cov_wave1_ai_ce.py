"""Wave-1 coverage tests for ai_knowledge/context_engine.py."""
from ai_knowledge.context_engine import ContextEngine, context_engine


def test_detect_intent_all_branches():
    cases = [
        ('مرحبا hello أهلا وسهلا', 'greeting'),
        ('أحتاج مساعدة help شرح how', 'help'),
        ('حلل analyze تقرير report المبيعات', 'analysis'),
        ('كم عدد العملاء what', 'data_query'),
        ('نسيت كلمة المرور password والمستخدم', 'security'),
        ('ضريبة tax الجمارك customs', 'tax_customs'),
        ('قطعة part محرك engine بستم', 'parts'),
        ('توقع predict تنبؤ forecast', 'prediction'),
        ('أنشئ create وثيقة document', 'create'),
        ('ابحث search أين أجد المنتج', 'search'),
        ('كلام عادي عن الطقس اليوم', 'general'),
    ]
    for msg, expected in cases:
        assert ContextEngine._detect_intent(msg.lower()) == expected, msg


def test_analyze_context_greeting_no_system_call():
    out = ContextEngine.analyze_context('مرحبا، كيف الحال؟')
    assert out['intent'] == 'greeting'
    assert out['confidence'] == 0.8
    assert out['entities'] == {
        'customer_name': None, 'product_name': None, 'date_range': None,
        'amount': None, 'user_name': None,
    }
    assert out['context_data']['user_role'] is False
    assert out['context_data']['system_state'] is None


def test_analyze_context_owner_flag():
    out = ContextEngine.analyze_context('مرحبا', context={'is_owner': True})
    assert out['context_data']['user_role'] is True


def test_analyze_context_data_query_loads_system_state(db):
    out = ContextEngine.analyze_context('كم عدد العملاء؟')
    assert out['intent'] == 'data_query'
    assert out['context_data']['system_state'] is not None


def test_enhance_response_prediction_branch():
    out = ContextEngine.enhance_response('توقع predict المبيعات', 'أساسي')
    assert out.startswith('أساسي')
    assert 'توقع المبيعات للأيام القادمة' in out
    assert 'توقع التدفق النقدي' in out


def test_enhance_response_create_branch():
    out = ContextEngine.enhance_response('أنشئ create وثيقة', 'أساسي')
    assert out.startswith('أساسي')
    assert 'تقارير مالية مفصلة' in out


def test_enhance_response_greeting_keeps_basic():
    out = ContextEngine.enhance_response('مرحبا أهلا', 'رد أساسي')
    assert out.startswith('رد أساسي')


def test_enhance_response_analysis_branch_runs(db, test_sale):
    out = ContextEngine.enhance_response('حلل analyze تقرير المبيعات', 'أساسي')
    assert out.startswith('أساسي')


def test_enhance_response_data_query_branch_runs(db, test_customer):
    out = ContextEngine.enhance_response('كم عدد العملاء what', 'أساسي')
    assert out.startswith('أساسي')


def test_enhance_response_search_branch_runs(db):
    out = ContextEngine.enhance_response('ابحث search عن المنتج', 'أساسي')
    assert out.startswith('أساسي')


def test_get_smart_suggestions_per_intent():
    analysis = ContextEngine.get_smart_suggestions('حلل analyze التقرير')
    assert any('المبيعات' in s for s in analysis)
    query = ContextEngine.get_smart_suggestions('كم عدد العملاء what')
    assert any('العملاء' in s for s in query)
    help_s = ContextEngine.get_smart_suggestions('مساعدة help كيف how')
    assert any('فاتورة' in s for s in help_s)
    default = ContextEngine.get_smart_suggestions('كلام عادي عن الطقس')
    assert 'حلل المبيعات' in default


def test_global_instance():
    assert isinstance(context_engine, ContextEngine)
