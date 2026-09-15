"""Wave-1 coverage tests for ai_knowledge/reasoning_engine.py (pure logic)."""
from ai_knowledge.reasoning_engine import ReasoningEngine, get_reasoning_engine


def make_engine():
    return ReasoningEngine()


def test_think_pricing_full_flow():
    eng = make_engine()
    ctx = {'cost_price': 100, 'customer_type': 'regular', 'quantity': 5,
           'margin': 1.30, 'discount': 0}
    out = eng.think('ما السعر المثالي لمنتج تكلفته 100 لعميل regular؟', ctx)
    assert out['problem_type'] == 'pricing'
    assert len(out['reasoning_steps']) == 4
    assert out['solution'] == 130.0
    assert out['confidence'] == 0.9
    assert out['verification']['is_valid'] is True
    assert len(out['alternatives']) == 2
    assert out['alternatives'][0]['solution'] == 130.0 * 0.95
    assert len(eng.reasoning_history) == 1


def test_think_general_flow():
    eng = make_engine()
    out = eng.think('Explain the project plan', None)
    assert out['problem_type'] == 'general'
    assert len(out['reasoning_steps']) == 4
    assert out['solution'] == 'يحتاج معلومات إضافية'
    assert out['alternatives'] == []
    assert out['verification']['is_valid'] is True


def test_think_error_path_returns_error_dict():
    eng = make_engine()
    out = eng.think(None, None)
    assert out['solution'] is None
    assert out['confidence'] == 0
    assert 'error' in out


def test_analyze_problem_types():
    eng = make_engine()
    cases = [
        ('optimize price pricing', 'pricing'),
        ('stock inventory check', 'inventory'),
        ('predict forecast sales', 'prediction'),
        ('journal accounting entry', 'accounting'),
        ('repair maintenance engine', 'maintenance'),
        ('customer client retention', 'customer'),
        ('something totally unrelated', 'general'),
    ]
    for problem, expected in cases:
        ptype, _ = eng._analyze_problem(problem, None)
        assert ptype == expected, problem


def test_analyze_problem_extracts_numbers_and_keywords():
    eng = make_engine()
    _, elements = eng._analyze_problem('سعر منتج 100 درهم لعميل بكمية 5 فاتورة', None)
    assert '100' in elements
    assert '5' in elements
    assert 'منتج' in elements
    assert 'عميل' in elements


def test_decompose_branches():
    eng = make_engine()
    pricing = eng._decompose_problem('what price?', [])
    assert pricing[0] == 'تحديد سعر التكلفة'
    assert len(pricing) == 4
    pred = eng._decompose_problem('توقع المبيعات', [])
    assert 'جمع البيانات التاريخية' in pred
    acc = eng._decompose_problem('قيد محاسبة عام', [])
    assert 'تحديد نوع القيد' in acc
    general = eng._decompose_problem('random topic', [])
    assert general[0] == 'فهم المشكلة'


def test_solve_step_cost_margin_quantity_final():
    eng = make_engine()
    assert eng._solve_step('تحديد سعر التكلفة', {'cost_price': 250})['solution'] == 250
    assert eng._solve_step('تحديد سعر التكلفة', None)['solution'] == 100
    assert eng._solve_step('تحديد نوع العميل والهامش', {'customer_type': 'merchant'})['solution'] == 1.20
    assert eng._solve_step('تحديد نوع العميل والهامش', {'customer_type': 'partner'})['solution'] == 1.15
    assert eng._solve_step('مراعاة حجم الطلب والخصومات', {'quantity': 60})['solution'] == 10
    assert eng._solve_step('مراعاة حجم الطلب والخصومات', {'quantity': 20})['solution'] == 5
    assert eng._solve_step('مراعاة حجم الطلب والخصومات', {'quantity': 2})['solution'] == 0
    final = eng._solve_step('حساب السعر النهائي المقترح',
                            {'cost_price': 100, 'margin': 1.2, 'discount': 10})
    assert final['solution'] == 108.0
    generic = eng._solve_step('خطوة غامضة', None)
    assert generic['solution'] == 'يحتاج معلومات إضافية'
    assert generic['confidence'] == 0.5


def test_combine_solutions():
    eng = make_engine()
    assert eng._combine_solutions([1, 2, 3, 99.5], 'pricing') == 99.5
    assert eng._combine_solutions([1], 'pricing') is None
    assert eng._combine_solutions(['a', 'b'], 'prediction') == 'b'
    assert eng._combine_solutions([], 'prediction') is None
    assert eng._combine_solutions(['x'], 'general') == 'x'
    assert eng._combine_solutions([], 'general') is None


def test_verify_solution_branches():
    eng = make_engine()
    ok = eng._verify_solution(150, 'price?', {'cost_price': 100})
    assert ok['is_valid'] is True and ok['confidence'] == 0.9
    neg = eng._verify_solution(-5, 'price?', None)
    assert neg['is_valid'] is False and neg['confidence'] == 0.0
    assert 'موجب' in neg['notes'][0]
    below = eng._verify_solution(80, 'price?', {'cost_price': 100})
    assert below['is_valid'] is False and below['confidence'] == 0.2
    thin = eng._verify_solution(103, 'price?', {'cost_price': 100})
    assert thin['is_valid'] is True and thin['confidence'] == 0.6
    non_numeric = eng._verify_solution('نص', 'q', None)
    assert non_numeric['is_valid'] is True


def test_generate_alternatives():
    eng = make_engine()
    alts = eng._generate_alternatives('q', None, 200.0)
    assert len(alts) == 2
    assert alts[0]['solution'] == 190.0
    assert alts[1]['solution'] == 210.0
    assert eng._generate_alternatives('q', None, 'نص') == []
    assert eng._generate_alternatives('q', None, None) == []


def test_chain_of_thought_structure():
    eng = make_engine()
    out = eng.chain_of_thought('ما سعر المنتج؟', {'cost_price': 50})
    assert out['method'] == 'chain_of_thought'
    assert out['question'] == 'ما سعر المنتج؟'
    assert len(out['thought_chain']) == 5
    assert out['thought_chain'][0]['step'] == 1
    assert 'cost_price' in out['thought_chain'][1]['thought']
    assert out['solution']['problem_type'] == 'pricing'


def test_mathematical_reasoning_operations():
    eng = make_engine()
    assert eng.mathematical_reasoning('10 + 20')['result'] == 30.0
    sub = eng.mathematical_reasoning('100 - 30')
    assert sub['operation'] == 'subtraction' and sub['result'] == 70.0
    mul = eng.mathematical_reasoning('6 * 7')
    assert mul['operation'] == 'multiplication' and mul['result'] == 42.0
    div = eng.mathematical_reasoning('100 / 4')
    assert div['operation'] == 'division' and div['result'] == 25.0
    pct = eng.mathematical_reasoning('خصم 200 نسبة 10%')
    assert pct['operation'] == 'percentage' and pct['result'] == 20.0
    unk = eng.mathematical_reasoning('hello world')
    assert unk['operation'] == 'unknown' and unk['result'] is None
    assert unk['confidence'] == 0.0


def test_mathematical_division_by_zero_safe():
    eng = make_engine()
    out = eng.mathematical_reasoning('10 / 0')
    assert out['operation'] == 'division'
    assert out['result'] == 0


def test_financial_reasoning_healthy():
    eng = make_engine()
    data = {'sales': 10000, 'costs': 6000, 'expenses': 2000,
            'assets': 50000, 'liabilities': 20000}
    out = eng.financial_reasoning('حلل الوضع المالي', data)
    assert out['metrics']['gross_margin'] == 40.0
    assert out['metrics']['net_profit'] == 2000
    assert out['metrics']['net_margin'] == 20.0
    assert out['metrics']['current_ratio'] == 2.5
    assert out['confidence'] == 0.9
    assert 'ممتاز' in out['recommendation']


def test_financial_reasoning_weak():
    eng = make_engine()
    data = {'sales': 1000, 'costs': 900, 'expenses': 200, 'assets': 500, 'liabilities': 1000}
    out = eng.financial_reasoning('حلل', data)
    assert out['metrics']['net_margin'] == -10.0
    assert 'منخفضة' in out['recommendation']
    assert any('خطر' in step for step in out['reasoning_steps'])


def test_financial_reasoning_empty_data():
    eng = make_engine()
    out = eng.financial_reasoning('حلل', {})
    assert out['metrics'] == {}
    assert out['confidence'] == 0.9
    assert 'منخفضة' in out['recommendation']


def test_technical_reasoning_branches():
    eng = make_engine()
    eng_out = eng.technical_reasoning('عطل في محرك engine المعدة')
    assert eng_out['priority'] == 'high'
    assert len(eng_out['possible_causes']) == 5
    assert len(eng_out['recommended_solutions']) == 5
    brake = eng.technical_reasoning('مشكلة فرامل brake')
    assert brake['priority'] == 'medium'
    assert 'فحمات' in brake['possible_causes'][0]
    oil = eng.technical_reasoning('تسريب زيت oil')
    assert 'الزيت' in oil['possible_causes'][0]
    unk = eng.technical_reasoning('شيء غريب غير معروف')
    assert unk['possible_causes'] == ['يحتاج معلومات أكثر للتشخيص الدقيق']


def test_business_reasoning_structure():
    eng = make_engine()
    out = eng.business_reasoning('خطة النمو', {})
    assert set(out['swot']) == {'strengths', 'weaknesses', 'opportunities', 'threats'}
    assert len(out['recommendations']) == 5
    assert len(out['action_plan']) == 2
    assert out['action_plan'][0]['priority'] == 'high'


def test_history_and_explain():
    eng = make_engine()
    assert eng.get_reasoning_history() == []
    eng.think('سعر price المنتج', {'cost_price': 10})
    eng.think('توقع predict المبيعات', None)
    hist = eng.get_reasoning_history(limit=1)
    assert len(hist) == 1
    assert hist[0]['problem'] == 'توقع predict المبيعات'
    text = eng.explain_decision('رفع السعر', {'الهامش': '30%', 'الطلب': 'مرتفع'})
    assert 'رفع السعر' in text
    assert 'الهامش: 30%' in text
    assert 'الطلب: مرتفع' in text


def test_singleton():
    assert get_reasoning_engine() is get_reasoning_engine()
