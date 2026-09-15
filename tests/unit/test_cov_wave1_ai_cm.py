"""Wave-1 coverage tests for ai_knowledge/conversation_manager.py (pure logic)."""
from ai_knowledge.conversation_manager import (
    ConversationManager, get_conversation_manager,
)


def make_manager():
    return ConversationManager()


def test_start_conversation_structure():
    mgr = make_manager()
    out = mgr.start_conversation(7, {'name': 'أحمد'})
    assert out['conversation_id'] == 7
    assert out['status'] == 'active'
    assert 'أحمد' in out['greeting']
    assert 'أزاد' in out['greeting']
    assert mgr.active_conversations[7]['style'] == 'professional'


def test_greeting_defaults_without_user_info():
    mgr = make_manager()
    out = mgr.start_conversation(8)
    assert 'عزيزي' in out['greeting']


def test_process_message_auto_starts_and_appends():
    mgr = make_manager()
    out = mgr.process_message(11, 'كم سعر المنتج 100؟')
    assert out['intent'] == 'pricing_query'
    assert out['context_updated'] is True
    assert out['confidence'] == 0.8
    assert 'الشبكات العصبية' in out['response']
    assert len(out['suggestions']) == 3
    history = mgr.get_conversation_history(11)
    assert len(history) == 2
    assert history[0]['role'] == 'user'
    assert history[1]['role'] == 'assistant'


def test_analyze_intent_all_branches():
    mgr = make_manager()
    cases = [
        ('كم سعر price المنتج؟', 'pricing_query'),
        ('توقع predict المبيعات forecast', 'prediction_query'),
        ('راجع قيد accounting المحاسبة', 'accounting_query'),
        ('إصلاح repair صيانة maintenance', 'maintenance_query'),
        ('حالة مخزون inventory stock', 'inventory_query'),
        ('بيانات عميل customer زبون', 'customer_query'),
        ('كيف how طريقة الاستخدام method', 'howto_query'),
        ('مرحبا، يوم جميل', 'general_query'),
    ]
    for msg, expected in cases:
        intent, _ = mgr._analyze_intent(msg)
        assert intent == expected, msg


def test_analyze_intent_entities():
    mgr = make_manager()
    _, entities = mgr._analyze_intent('سعر منتج رقم 12345 للعميل')
    assert entities['numbers'] == ['12345']
    assert entities['entity_type'] == 'product'
    _, entities2 = mgr._analyze_intent('ملف عميل جديد')
    assert entities2['entity_type'] == 'customer'
    _, entities3 = mgr._analyze_intent('مرحبا')
    assert entities3 == {}


def test_generate_response_per_intent_confidence():
    mgr = make_manager()
    mgr.start_conversation(21)
    expected = {
        'pricing_query': (0.8, 'الشبكات العصبية'),
        'prediction_query': (0.9, 'نموذج عصبي'),
        'maintenance_query': (0.85, 'مهندس صيانة'),
        'accounting_query': (0.95, 'محاسب قانوني'),
        'general_query': (0.6, 'فهمت سؤالك'),
    }
    for intent, (conf, snippet) in expected.items():
        resp = mgr._generate_response(21, 'msg', intent, {})
        assert resp['confidence'] == conf, intent
        assert snippet in resp['text'], intent
        assert resp['style'] == 'professional'


def test_update_context_caps_intent_history():
    mgr = make_manager()
    mgr.start_conversation(31)
    for i in range(12):
        mgr.process_message(31, f'رسالة رقم {i} عن السعر price')
    ctx = mgr.active_conversations[31]['context']
    assert ctx['last_intent'] == 'pricing_query'
    assert len(ctx['intent_history']) == 10
    assert 'updated_at' in ctx


def test_generate_suggestions_per_intent():
    mgr = make_manager()
    pricing = mgr._generate_suggestions('pricing_query', {})
    assert any('السعر' in s for s in pricing)
    pred = mgr._generate_suggestions('prediction_query', {})
    assert any('المبيعات' in s for s in pred)
    maint = mgr._generate_suggestions('maintenance_query', {})
    assert any('الصيانة' in s for s in maint)
    default = mgr._generate_suggestions('general_query', {})
    assert any('المخزون' in s for s in default)
    for group in (pricing, pred, maint, default):
        assert len(group) <= 3


def test_get_conversation_history_unknown_and_limit():
    mgr = make_manager()
    assert mgr.get_conversation_history(999) == []
    mgr.start_conversation(41)
    for _ in range(3):
        mgr.process_message(41, 'كم السعر price؟')
    assert len(mgr.get_conversation_history(41)) == 6
    assert len(mgr.get_conversation_history(41, limit=2)) == 2


def test_end_conversation_summary_and_farewell():
    mgr = make_manager()
    mgr.start_conversation(51)
    mgr.process_message(51, 'كم السعر price؟')
    mgr.process_message(51, 'توقع predict المبيعات')
    out = mgr.end_conversation(51)
    assert out['summary']['messages_count'] == 4
    assert set(out['summary']['topics']) == {'pricing_query', 'prediction_query'}
    assert 'أزاد' in out['farewell']
    assert 51 not in mgr.active_conversations


def test_end_conversation_unknown_user():
    mgr = make_manager()
    assert mgr.end_conversation(12345) == {'error': 'No active conversation'}


def test_conversation_styles_registered():
    mgr = make_manager()
    assert set(mgr.conversation_styles) == {'professional', 'friendly', 'technical', 'simple'}


def test_singleton():
    assert get_conversation_manager() is get_conversation_manager()
