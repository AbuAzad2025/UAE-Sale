"""Wave-1 coverage tests for ai_knowledge/code_generator.py (pure logic)."""
from ai_knowledge.code_generator import CodeGenerator, get_code_generator


def make_gen():
    return CodeGenerator()


def test_templates_loaded():
    gen = make_gen()
    assert set(gen.templates) == {
        'sql_select', 'sql_insert', 'sql_update', 'python_function', 'api_endpoint',
    }
    assert gen.generated_code_history == []


def test_generate_sql_select_full_filters():
    gen = make_gen()
    q = gen.generate_sql_query('select', 'sales', {
        'columns': 'id, amount_base',
        'where': {'status': 'confirmed'},
        'order_by': 'sale_date DESC',
        'limit': 10,
    })
    assert q == ("SELECT id, amount_base FROM sales WHERE status = 'confirmed'"
                 ' ORDER BY sale_date DESC LIMIT 10')


def test_generate_sql_select_no_filters():
    gen = make_gen()
    assert gen.generate_sql_query('select', 'products') == 'SELECT * FROM products WHERE 1=1'


def test_generate_sql_select_escapes_quotes():
    gen = make_gen()
    q = gen.generate_sql_query('select', 'customers', {'where': {'name': "O'Brien"}})
    assert "O''Brien" in q


def test_generate_sql_insert():
    gen = make_gen()
    q = gen.generate_sql_query('insert', 'products', {
        'columns': ['name', 'price'], 'values': ["Brake Pad", 100],
    })
    assert q == "INSERT INTO products (name, price) VALUES ('Brake Pad', 100)"


def test_generate_sql_update():
    gen = make_gen()
    q = gen.generate_sql_query('update', 'products', {
        'set': {'price': 120}, 'where': {'id': 3},
    })
    assert q == "UPDATE products SET price = '120' WHERE id = '3'"


def test_generate_sql_unsupported_and_error():
    gen = make_gen()
    assert gen.generate_sql_query('delete', 'sales') == '-- Unsupported intent: delete'
    assert gen.generate_sql_query('select', 't', 'not-a-dict').startswith('-- Error:')


def test_generate_python_calculate():
    gen = make_gen()
    code = gen.generate_python_function('calc_margin', 'حساب هامش الربح', ['cost', 'price'])
    assert code.startswith('def calc_margin(cost, price):')
    assert 'حساب هامش الربح' in code
    assert 'result = 0' in code


def test_generate_python_predict_search_default():
    gen = make_gen()
    pred = gen.generate_python_function('f', 'predict sales')
    assert 'AIService' in pred
    search = gen.generate_python_function('f', 'بحث عن منتج')
    assert 'Product.query' in search
    default = gen.generate_python_function('f', 'do something else')
    assert 'return None' in default
    no_params = gen.generate_python_function('f', 'calculate x')
    assert 'def f():' in no_params


def test_generate_report_sales_inventory_customers():
    gen = make_gen()
    sales = gen.generate_report_query('sales', {'start_date': '2026-01-01', 'end_date': '2026-01-31'})
    assert 'FROM sales' in sales
    assert '2026-01-01' in sales and '2026-01-31' in sales
    inv = gen.generate_report_query('inventory')
    assert 'stock_value' in inv
    cust = gen.generate_report_query('customers')
    assert 'total_purchases' in cust


def test_generate_report_sales_missing_range_and_unknown():
    gen = make_gen()
    assert gen.generate_report_query('sales') == '-- Missing date range'
    assert gen.generate_report_query('weird') == '-- Unknown report type: weird'


def test_generate_report_escapes_quotes():
    gen = make_gen()
    q = gen.generate_report_query('sales', {'start_date': "2026' OR '1'='1", 'end_date': '2026-01-31'})
    assert "2026'' OR ''1''=''1" in q


def test_fix_code_quote_error():
    gen = make_gen()
    out = gen.fix_code("x = 'hi", "SyntaxError: unterminated quote string")
    assert out['fixed_code'] == 'x = "hi'
    assert out['changes'] == ['تم تصحيح الاقتباسات']
    assert out['confidence'] == 0.7


def test_fix_code_indentation_error():
    gen = make_gen()
    out = gen.fix_code('def f():\n     x = 1', 'IndentationError: bad indent')
    assert 'تم تصحيح المسافات البادئة' in out['changes']
    assert out['fixed_code'].splitlines()[0] == 'def f():'


def test_fix_code_missing_import():
    gen = make_gen()
    out = gen.fix_code('x = db.session', "NameError: name 'db' is not defined")
    assert out['fixed_code'].startswith('from extensions import db')
    assert any('db' in c for c in out['changes'])


def test_fix_code_unknown_error_no_changes():
    gen = make_gen()
    out = gen.fix_code('x = 1', 'TypeError: unsupported operand')
    assert out['fixed_code'] == 'x = 1'
    assert out['changes'] == []
    assert out['confidence'] == 0.3
    assert out['explanation'].startswith('تم تحليل الخطأ')


def test_optimize_code_all_hints():
    gen = make_gen()
    code = ('items = []\nfor x in rows:\n    items.append(x)\n'
            'db.session.add(a)\ndb.session.add(b)\n'
            'Product.query.filter(True).all()')
    out = gen.optimize_code(code)
    assert len(out['improvements']) == 2
    assert out['performance_gain_percent'] == 30
    assert out['optimized_code'] == code


def test_optimize_code_bulk_and_clean():
    gen = make_gen()
    bulk = '\n'.join(f'db.session.add(o{i})' for i in range(6))
    out = gen.optimize_code(bulk)
    assert any('bulk_insert' in imp for imp in out['improvements'])
    clean = gen.optimize_code('x = 1\nreturn x')
    assert clean['improvements'] == []
    assert clean['performance_gain_percent'] == 0


def test_singleton():
    assert get_code_generator() is get_code_generator()
