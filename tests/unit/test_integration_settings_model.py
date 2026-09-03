"""Unit tests for models/integration_settings.py — service config store."""
import pytest

from models import IntegrationSettings
from extensions import db as _db


class TestGetServiceConfig:
    def test_creates_default_record_when_missing(self, db):
        rec = IntegrationSettings.get_service_config('whatsapp')
        assert rec.id is not None
        assert rec.service_name == 'whatsapp'
        assert rec.enabled is False
        assert rec.get_config() == {}

    def test_returns_existing_record(self, db):
        first = IntegrationSettings.get_service_config('email')
        second = IntegrationSettings.get_service_config('email')
        assert first.id == second.id


class TestConfigAccessors:
    def _rec(self, db, **kw):
        rec = IntegrationSettings(service_name='svc', enabled=True,
                                  config_data='{"a": 1}')
        for k, v in kw.items():
            setattr(rec, k, v)
        _db.session.add(rec)
        _db.session.flush()
        return rec

    def test_get_config_parses_json(self, db):
        assert self._rec(db).get_config() == {'a': 1}

    def test_get_config_bad_json_returns_empty(self, db):
        assert self._rec(db, config_data='{broken').get_config() == {}

    def test_get_config_none_returns_empty(self, db):
        assert self._rec(db, config_data=None).get_config() == {}

    def test_set_config_serializes(self, db):
        rec = self._rec(db)
        rec.set_config({'k': 'قيمة'})
        import json
        assert json.loads(rec.config_data) == {'k': 'قيمة'}

    def test_value_roundtrip_with_default(self, db):
        rec = self._rec(db)
        assert rec.get_value('missing', 'dflt') == 'dflt'
        rec.set_value('token', 'abc')
        assert rec.get_value('token') == 'abc'
        assert rec.get_config()['token'] == 'abc'

    def test_repr_marks_enabled_state(self, db):
        assert '✅' in repr(self._rec(db))
        assert '❌' in repr(self._rec(db, service_name='off', enabled=False))

    def test_to_dict(self, db):
        d = self._rec(db).to_dict()
        assert d['service_name'] == 'svc'
        assert d['enabled'] is True
        assert d['config'] == {'a': 1}
        assert d['last_tested_at'] is None
        assert isinstance(d['updated_at'], str) and 'T' in d['updated_at']
