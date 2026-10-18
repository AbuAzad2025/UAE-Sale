"""Regression coverage for the AI endpoints that used to answer 500.

routes/ai.py registers fifty routes. Twelve of them - deep-analysis,
cash-flow-prediction, smart-price, churn-prediction, learning/status,
learning/evolve, improvement/auto-improve, improvement/progress,
improvement/set-goal, knowledge/add-website, knowledge/add-document and
upload-excel - were never requested by any test, and when they were requested
as an owner they failed:

  * eight of the twelve call module-level `learning_system` /
    `self_improvement` objects rather than AIService, so a hasattr check on
    AIService reports the wrong thing entirely;
  * four call AIService methods that do not exist (predict_cash_flow and
    perform_self_improvement are the names that actually exist), so they raise
    AttributeError;
  * learning/evolve died inside the learning system on `set(contexts)` where
    the contexts are dicts, which cannot be hashed.

Nothing caught any of it because the census only counts routes that answered,
so an endpoint that 500s is indistinguishable from one nobody linked to. These
tests ask for each one as an owner and fail on 500, which is the assertion that
would have caught them.
"""
import pytest

# (method, path, json body or None). Bodies are supplied where the endpoint's
# own validation needs them; the point is that the endpoint reaches its
# validation instead of raising.
ROUTES = [
    ('GET', '/ai/deep-analysis', None),
    ('GET', '/ai/cash-flow-prediction?days=30', None),
    ('POST', '/ai/smart-price',
     {'product_id': None, 'customer_id': None, 'quantity': 1}),
    ('GET', '/ai/churn-prediction', None),
    ('GET', '/ai/learning/status', None),
    ('POST', '/ai/learning/evolve', None),
    ('GET', '/ai/improvement/status', None),
    ('POST', '/ai/improvement/auto-improve', None),
    ('GET', '/ai/improvement/progress', None),
    ('POST', '/ai/improvement/set-goal',
     {'area': 'accuracy', 'target_score': 90, 'timeframe': '30_days'}),
    ('POST', '/ai/knowledge/add-website',
     {'url': 'https://example.com', 'topic': 'test'}),
    ('POST', '/ai/knowledge/add-document',
     {'title': 'test', 'content': 'hello world', 'source': 'test'}),
    ('POST', '/ai/upload-excel', None),
]


@pytest.mark.parametrize('method,path,body', ROUTES,
                         ids=[p for _, p, _ in ROUTES])
def test_ai_endpoint_does_not_error(client, db, owner, login_as,
                                    method, path, body):
    """Every AI endpoint must answer with a real response, never a 500."""
    login_as('owner')
    kw = {'json': body} if body is not None else {}
    r = client.open(path, method=method, **kw)

    assert r.status_code != 500, (
        f'{method} {path} answered 500: {r.get_data(as_text=True)[:200]}')
    assert r.status_code in (200, 400, 404), (
        f'{method} {path} answered an unexpected {r.status_code}')


@pytest.mark.parametrize('method,path', [
    ('POST', '/ai/smart-price'),
    ('POST', '/ai/improvement/set-goal'),
], ids=['smart-price', 'improvement-set-goal'])
def test_ai_post_without_body_validates(client, db, owner, login_as,
                                       method, path):
    """A body-less POST must reach validation, not raise on get_json().

    Both handlers called request.get_json(), which raises when there is no
    body. smart_price had no handler at all, so the AttributeError surfaced as
    an uncaught 500.
    """
    login_as('owner')
    r = client.open(path, method=method)

    assert r.status_code == 400, (
        f'{path} with no body answered {r.status_code} instead of 400')
    # The two handlers report differently - smart_price returns only an
    # 'error', set_improvement_goal also sets 'success': False - so the
    # invariant to hold is that the request was rejected with a reason.
    assert r.get_json().get('error'), (
        f'{path} answered 400 without an error message')


def test_smart_price_prices_a_real_product(client, db, owner, login_as,
                                           product, customer):
    """smart-price must return a price for a product that exists."""
    login_as('owner')
    r = client.post('/ai/smart-price', json={
        'product_id': product.id,
        'customer_id': customer.id,
        'quantity': 2,
    })

    assert r.status_code == 200, (
        f'smart-price answered {r.status_code} for a real product: '
        f'{r.get_data(as_text=True)[:200]}')
    pricing = r.get_json()
    assert pricing.get('predicted_price') is not None, (
        f'smart-price returned no predicted_price: {pricing}')


def test_churn_watchlist_scores_real_customers(client, db, owner, login_as,
                                               customer):
    """The churn watchlist must aggregate real rows, not just avoid crashing."""
    login_as('owner')
    r = client.get('/ai/churn-prediction')

    assert r.status_code == 200
    body = r.get_json()
    assert body['customers_analyzed'] >= 1, (
        f'churn watchlist analysed no customers although one exists: {body}')
    assert body['customers'], (
        f'churn watchlist returned no scored customers: {body}')

    top = body['customers'][0]
    assert top['customer_id'] == customer.id
    assert top['risk_level'] in ('low', 'medium', 'high')
    assert 0.0 <= top['churn_risk_score'] <= 1.0


def test_cash_flow_prediction_converts_days_to_months(client, db, owner,
                                                      login_as):
    """The route asks for days; the neural engine forecasts by month."""
    login_as('owner')
    r = client.get('/ai/cash-flow-prediction?days=90')
    body = r.get_json()

    assert r.status_code == 200
    assert body['requested_days'] == 90
    assert body['months_ahead'] == 3, (
        f'90 days should map to 3 months, got {body["months_ahead"]}')


def test_evolution_deduplicates_dict_contexts(client, db, owner, login_as):
    """evolve_knowledge must survive dict-valued interaction contexts.

    _improve_context_understanding used list(set(contexts)) on a list of dicts,
    which raises TypeError: unhashable type. This drives it past that branch
    rather than only exercising the empty case that happened to pass.
    """
    from ai_knowledge.learning_system import learning_system

    login_as('owner')
    learning_system.interactions.extend(
        {'question': 'what is the turbo pressure',
         'context': {'page': 'products', 'role': 'owner'},
         'response': 'x', 'timestamp': 'now'}
        for _ in range(5)
    )

    r = client.post('/ai/learning/evolve')

    assert r.status_code == 200, (
        f'evolve answered {r.status_code}: {r.get_data(as_text=True)[:200]}')
    evolution = r.get_json()['evolution']
    assert evolution['context_improved'] is True

    understood = learning_system.learned_knowledge.get(
        'context_understanding', {})
    for question_type, entry in understood.items():
        assert len(entry['common_contexts']) == len(
            {str(c) for c in entry['common_contexts']}), (
            f'{question_type} kept duplicate contexts')