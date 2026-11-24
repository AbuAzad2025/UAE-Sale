"""Cache serializer must never store a bare None that breaks get()."""
import os
import pickle
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_failed_pickle_stores_readable_none():
    src = open(os.path.join(ROOT, 'extensions.py'), encoding='utf-8').read()
    assert 'return pickle.dumps(None, protocol)' in src
    assert 'return None' not in src.split('def patched_dumps')[1].split('BaseSerializer.dumps')[0]


def test_roundtrip():
    payload = pickle.dumps(None, pickle.HIGHEST_PROTOCOL)
    assert pickle.loads(payload) is None
