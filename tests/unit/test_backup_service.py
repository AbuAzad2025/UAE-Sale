"""Unit tests for BackupService and trigger_backup entrypoint."""
import contextlib
import gzip
import hashlib
import json
import os
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.modules.setdefault('export_json_db', types.SimpleNamespace(export_db_to_json=lambda: None))

from services.backup_service import BackupService  # noqa: E402
import trigger_backup  # noqa: E402


def _write_gz(path, payload=b'-- fake sql dump'):
    with gzip.open(path, 'wb') as fh:
        fh.write(payload)


def _write_meta(path, timestamp='20250101_000001', manual=False, size=None):
    meta = {
        'filename': Path(path).name,
        'path': str(path),
        'timestamp': timestamp,
        'datetime': '2025-01-01T00:00:01',
        'size': size if size is not None else 64,
        'size_mb': round((size or 64) / (1024 * 1024), 6),
        'manual': manual,
        'compressed': True,
    }
    with open(str(path) + '.meta.json', 'w', encoding='utf-8') as fh:
        json.dump(meta, fh)
    return meta


def _make_backup(directory, name, timestamp, manual=False, size=64):
    path = Path(directory) / name
    _write_gz(path)
    _write_meta(path, timestamp=timestamp, manual=manual, size=size)
    return path


class _FakeCompleted:
    def __init__(self, returncode=0, stderr=''):
        self.returncode = returncode
        self.stdout = ''
        self.stderr = stderr


class _FakePopenProc:
    def __init__(self, returncode=0, stdin=None):
        self.returncode = returncode
        self._stdin = stdin
        self.stdout = b''
        self.stderr = b''

    def communicate(self):
        if self._stdin is not None:
            self.stdout = self._stdin.read()
        if self.returncode != 0:
            self.stderr = b'psql exploded'
        return self.stdout, self.stderr


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir()
    instance_dir = tmp_path / 'instance'
    instance_dir.mkdir()
    monkeypatch.setattr(BackupService, 'BACKUP_DIR', str(backup_dir))
    monkeypatch.setattr(BackupService, '_BASEDIR', str(tmp_path))
    monkeypatch.setattr(BackupService, 'MAX_BACKUPS', 5)
    return backup_dir


@pytest.fixture
def pg_env(monkeypatch):
    for key in ('PGPASSWORD', 'PGHOST', 'PGPORT', 'PGUSER', 'PGDATABASE'):
        monkeypatch.setenv(key, '')
    return None


class TestInitialize:
    def test_initialize_creates_directory(self, tmp_path, monkeypatch):
        target = tmp_path / 'nested' / 'backups'
        monkeypatch.setattr(BackupService, 'BACKUP_DIR', str(target))
        assert BackupService.initialize() is True
        assert target.is_dir()

    def test_initialize_failure_returns_false(self, tmp_path, monkeypatch):
        blocker = tmp_path / 'blocker'
        blocker.write_text('x', encoding='utf-8')
        monkeypatch.setattr(BackupService, 'BACKUP_DIR', str(blocker / 'sub'))
        assert BackupService.initialize() is False


class TestScheduleSettings:
    def test_defaults_when_no_file(self, backup_env):
        settings = BackupService.get_schedule_settings()
        assert settings == {
            'enabled': True,
            'frequency': 'daily',
            'backup_time': '02:00',
            'keep_count': 5,
        }

    def test_save_and_load_roundtrip_including_disabled_flag(self, backup_env):
        assert BackupService.save_schedule_settings({
            'enabled': False,
            'frequency': 'weekly',
            'backup_time': '03:30',
            'keep_count': 9,
        }) is True

        settings = BackupService.get_schedule_settings()
        assert settings['enabled'] is False
        assert settings['frequency'] == 'weekly'
        assert settings['backup_time'] == '03:30'
        assert settings['keep_count'] == 9

        raw = json.loads((backup_env.parent / 'instance' / 'backup_settings.json').read_text(
            encoding='utf-8'))
        assert raw['enabled'] is False

    def test_save_normalizes_types(self, backup_env):
        assert BackupService.save_schedule_settings({
            'enabled': '', 'frequency': 7, 'backup_time': None, 'keep_count': '3',
        }) is True
        settings = BackupService.get_schedule_settings()
        assert settings['enabled'] is False
        assert settings['frequency'] == '7'
        assert settings['keep_count'] == 3

    def test_load_json_file_missing_or_corrupt_returns_none(self, backup_env):
        missing = str(backup_env.parent / 'instance' / 'nope.json')
        assert BackupService._load_json_file(missing) is None

        bad = backup_env.parent / 'instance' / 'bad.json'
        bad.write_text('{not json', encoding='utf-8')
        assert BackupService._load_json_file(str(bad)) is None


class TestParsePostgresParams:
    @staticmethod
    def _install_db(monkeypatch, url):
        fake_db = SimpleNamespace(engine=SimpleNamespace(url=url))
        monkeypatch.setattr('extensions.db', fake_db)

    def test_none_for_sqlite_url(self, monkeypatch):
        self._install_db(monkeypatch, SimpleNamespace(drivername='sqlite', host=None))
        assert BackupService._parse_postgres_params() is None

    def test_normalizes_localhost_and_default_port(self, monkeypatch):
        url = SimpleNamespace(
            drivername='postgresql+psycopg2', host='localhost', port=None,
            username='admin', password='secret', database='/salesdb',
        )
        self._install_db(monkeypatch, url)
        params = BackupService._parse_postgres_params()
        assert params['host'] == '127.0.0.1'
        assert params['port'] == '5432'
        assert params['username'] == 'admin'
        assert params['password'] == 'secret'
        assert params['dbname'] == 'salesdb'

    def test_remote_host_and_empty_password(self, monkeypatch):
        url = SimpleNamespace(
            drivername='postgres', host='db.example.com', port=6543,
            username='u1', password=None, database='erp',
        )
        self._install_db(monkeypatch, url)
        params = BackupService._parse_postgres_params()
        assert params['host'] == 'db.example.com'
        assert params['port'] == '6543'
        assert params['password'] == ''

    def test_missing_username_returns_none(self, monkeypatch):
        url = SimpleNamespace(
            drivername='postgresql', host='h', port=5432,
            username=None, password='p', database='d',
        )
        self._install_db(monkeypatch, url)
        assert BackupService._parse_postgres_params() is None

    def test_missing_dbname_returns_none(self, monkeypatch):
        url = SimpleNamespace(
            drivername='postgresql', host='h', port=5432,
            username='u', password='p', database='',
        )
        self._install_db(monkeypatch, url)
        assert BackupService._parse_postgres_params() is None

    def test_engine_error_returns_none(self, monkeypatch):
        class _ExplodingDb:
            @property
            def engine(self):
                raise RuntimeError('no engine')

        monkeypatch.setattr('extensions.db', _ExplodingDb())
        assert BackupService._parse_postgres_params() is None


class TestListBackups:
    def test_fallback_metadata_without_meta_file(self, backup_env):
        _write_gz(backup_env / 'auto_backup_20250102_030405.sql.gz')
        backups = BackupService.list_backups()
        assert len(backups) == 1
        info = backups[0]
        assert info['filename'] == 'auto_backup_20250102_030405.sql.gz'
        assert info['timestamp'] == '20250102_030405'
        assert info['manual'] is False
        assert info['compressed'] is True
        assert info['size'] > 0

    def test_dump_files_are_candidates_and_not_compressed(self, backup_env):
        (backup_env / 'custom_dump.dump').write_bytes(b'PGDMP')
        backups = BackupService.list_backups()
        assert [b['filename'] for b in backups] == ['custom_dump.dump']
        assert backups[0]['compressed'] is False
        assert backups[0]['timestamp'] == 'custom_dump'

    def test_meta_json_preferred_over_fallback(self, backup_env):
        path = _make_backup(backup_env, 'auto_backup_20250101_000001.sql.gz', '20250101_000001')
        backups = BackupService.list_backups()
        assert backups[0]['timestamp'] == '20250101_000001'
        assert os.path.exists(str(path) + '.meta.json')

    def test_sorted_newest_first_by_mtime(self, backup_env):
        old = backup_env / 'auto_backup_20250101_000000.sql.gz'
        new = backup_env / 'auto_backup_20250102_000000.sql.gz'
        _write_gz(old)
        _write_gz(new)
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        names = [b['filename'] for b in BackupService.list_backups()]
        assert names == [
            'auto_backup_20250102_000000.sql.gz',
            'auto_backup_20250101_000000.sql.gz',
        ]

    def test_auto_only_and_manual_only_filters(self, backup_env):
        _make_backup(backup_env, 'auto_backup_20250101_000001.sql.gz', '20250101_000001')
        _make_backup(backup_env, 'manual_backup_20250102_000002.sql.gz', '20250102_000002', manual=True)

        auto_names = [b['filename'] for b in BackupService.list_backups(auto_only=True)]
        manual_names = [b['filename'] for b in BackupService.list_backups(manual_only=True)]
        all_names = [b['filename'] for b in BackupService.list_backups()]

        assert auto_names == ['auto_backup_20250101_000001.sql.gz']
        assert manual_names == ['manual_backup_20250102_000002.sql.gz']
        assert len(all_names) == 2

    def test_corrupt_meta_falls_back_to_defaults(self, backup_env):
        path = backup_env / 'manual_backup_20250103_000003.sql.gz'
        _write_gz(path)
        (Path(str(path) + '.meta.json')).write_text('broken{', encoding='utf-8')
        backups = BackupService.list_backups()
        assert backups[0]['manual'] is True
        assert backups[0]['timestamp'] == '20250103_000003'


class TestVerifyBackup:
    def test_missing_file_false(self, backup_env):
        assert BackupService.verify_backup('ghost.sql.gz') is False

    def test_zero_byte_file_false(self, backup_env):
        (backup_env / 'plain.sql').write_bytes(b'')
        assert BackupService.verify_backup('plain.sql') is False

    def test_corrupt_gzip_false(self, backup_env):
        (backup_env / 'broken.sql.gz').write_bytes(b'this is not gzip at all')
        assert BackupService.verify_backup('broken.sql.gz') is False

    def test_valid_gzip_with_matching_checksum_true(self, backup_env):
        path = backup_env / 'good.sql.gz'
        _write_gz(path, b'CREATE TABLE t(id int);')
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        meta = {'checksum': checksum}
        with open(str(path) + '.meta.json', 'w', encoding='utf-8') as fh:
            json.dump(meta, fh)
        assert BackupService.verify_backup('good.sql.gz') is True

    def test_checksum_mismatch_false(self, backup_env):
        path = backup_env / 'tampered.sql.gz'
        _write_gz(path, b'SELECT 1;')
        _write_meta(path, timestamp='20250104_000004')
        with open(str(path) + '.meta.json', 'r', encoding='utf-8') as fh:
            meta = json.load(fh)
        meta['checksum'] = 'deadbeef' * 8
        with open(str(path) + '.meta.json', 'w', encoding='utf-8') as fh:
            json.dump(meta, fh)
        assert BackupService.verify_backup('tampered.sql.gz') is False

    def test_valid_gzip_without_meta_true(self, backup_env):
        path = backup_env / 'nometa.sql.gz'
        _write_gz(path, b'DATA')
        assert BackupService.verify_backup('nometa.sql.gz') is True


class TestDeleteBackup:
    def test_removes_file_and_meta(self, backup_env):
        path = _make_backup(backup_env, 'auto_backup_20250101_000001.sql.gz', '20250101_000001')
        assert BackupService.delete_backup(path.name) is True
        assert not path.exists()
        assert not os.path.exists(str(path) + '.meta.json')

    def test_missing_file_still_succeeds_idempotent(self, backup_env):
        assert BackupService.delete_backup('never_existed.sql.gz') is True

    def test_deletion_failure_returns_false(self, backup_env):
        blocker = backup_env / 'auto_backup_blocked.sql.gz'
        blocker.mkdir()
        assert BackupService.delete_backup(blocker.name) is False
        assert blocker.is_dir()


class TestRetentionRotation:
    def test_keeps_n_newest_autos_and_never_touches_manuals(self, backup_env, monkeypatch):
        monkeypatch.setattr(BackupService, 'MAX_BACKUPS', 2)
        old1 = _make_backup(backup_env, 'auto_backup_20250101_000001.sql.gz', '20250101_000001')
        old2 = _make_backup(backup_env, 'auto_backup_20250102_000002.sql.gz', '20250102_000002')
        keep1 = _make_backup(backup_env, 'auto_backup_20250103_000003.sql.gz', '20250103_000003')
        keep2 = _make_backup(backup_env, 'auto_backup_20250104_000004.sql.gz', '20250104_000004')
        manual = _make_backup(
            backup_env, 'manual_backup_20250101_000009.sql.gz', '20250101_000009', manual=True)

        BackupService._cleanup_old_backups()

        assert not old1.exists() and not os.path.exists(str(old1) + '.meta.json')
        assert not old2.exists() and not os.path.exists(str(old2) + '.meta.json')
        assert keep1.exists() and keep2.exists()
        assert manual.exists()

        remaining = [b['filename'] for b in BackupService.list_backups()]
        assert sorted(remaining) == sorted([
            keep1.name, keep2.name, manual.name,
        ])

    def test_respects_keep_count_from_schedule_settings(self, backup_env):
        assert BackupService.save_schedule_settings({'keep_count': 1}) is True
        a = _make_backup(backup_env, 'auto_backup_20250101_000001.sql.gz', '20250101_000001')
        b = _make_backup(backup_env, 'auto_backup_20250102_000002.sql.gz', '20250102_000002')
        c = _make_backup(backup_env, 'auto_backup_20250103_000003.sql.gz', '20250103_000003')

        BackupService._cleanup_old_backups()

        assert not a.exists() and not b.exists()
        assert c.exists()

    def test_noop_when_under_limit(self, backup_env, monkeypatch):
        monkeypatch.setattr(BackupService, 'MAX_BACKUPS', 5)
        only = _make_backup(backup_env, 'auto_backup_20250105_000005.sql.gz', '20250105_000005')
        BackupService._cleanup_old_backups()
        assert only.exists()


class TestGetBackupStats:
    def test_counts_sizes_and_latest(self, backup_env):
        auto = _make_backup(
            backup_env, 'auto_backup_20250101_000001.sql.gz', '20250101_000001', size=100)
        manual = _make_backup(
            backup_env, 'manual_backup_20250102_000002.sql.gz', '20250102_000002',
            manual=True, size=2000100)
        os.utime(auto, (1000, 1000))
        os.utime(manual, (2000, 2000))

        stats = BackupService.get_backup_stats()

        assert stats['total_count'] == 2
        assert stats['auto_count'] == 1
        assert stats['manual_count'] == 1
        assert stats['total_size_mb'] == round(2000200 / (1024 * 1024), 2)
        assert stats['latest_backup']['filename'] == manual.name

    def test_empty_state(self, backup_env):
        stats = BackupService.get_backup_stats()
        assert stats['total_count'] == 0
        assert stats['latest_backup'] is None
        assert stats['total_size_mb'] == 0

    def test_exception_safe_zeroed_result(self, backup_env, monkeypatch):
        def _boom(*args, **kwargs):
            raise ValueError('disk exploded')

        monkeypatch.setattr(BackupService, 'list_backups', staticmethod(_boom))
        stats = BackupService.get_backup_stats()
        assert stats == {
            'total_count': 0,
            'manual_count': 0,
            'auto_count': 0,
            'total_size_mb': 0,
            'latest_backup': None,
        }


class TestCreateBackup:
    @staticmethod
    def _fake_run(content, returncode=0, raise_fnf=False):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(list(cmd))
            if raise_fnf:
                raise FileNotFoundError(cmd[0])
            if returncode == 0:
                Path(cmd[-1]).write_bytes(content.encode('utf-8'))
            return _FakeCompleted(returncode=returncode, stderr='pg_dump: FATAL bad things')

        return runner, calls

    def _install_params(self, monkeypatch, host='127.0.0.1', port='5432'):
        params = {
            'host': host, 'port': port, 'username': 'admin',
            'password': 'secret', 'dbname': 'salesdb',
        }
        monkeypatch.setattr(BackupService, '_parse_postgres_params', staticmethod(lambda: params))
        return params

    def test_success_returns_metadata_writes_gz_and_manifest(
        self, backup_env, pg_env, monkeypatch
    ):
        self._install_params(monkeypatch)
        runner, calls = self._fake_run('-- schema\nCREATE TABLE t();')
        monkeypatch.setattr(subprocess, 'run', runner)

        metadata = BackupService.create_backup(manual=False, description='nightly')

        assert metadata is not None
        assert metadata['filename'].startswith('auto_backup_')
        assert metadata['filename'].endswith('.sql.gz')
        assert metadata['type'] == 'postgresql_sql_gz'
        assert metadata['compressed'] is True
        assert metadata['encrypted'] is False
        assert metadata['manual'] is False
        assert metadata['description'] == 'nightly'
        assert datetime.strptime(metadata['timestamp'], '%Y%m%d_%H%M%S')

        backup_file = Path(metadata['path'])
        assert backup_file.exists()
        assert gzip.decompress(backup_file.read_bytes()) == b'-- schema\nCREATE TABLE t();'
        assert metadata['size'] == backup_file.stat().st_size
        assert metadata['size_mb'] == round(metadata['size'] / (1024 * 1024), 2)
        assert metadata['checksum'] == hashlib.sha256(backup_file.read_bytes()).hexdigest()

        manifest = json.loads(Path(str(backup_file) + '.meta.json').read_text(encoding='utf-8'))
        assert manifest['filename'] == metadata['filename']
        assert manifest['checksum'] == metadata['checksum']

        cmd = calls[0]
        assert '--no-owner' in cmd and '--no-privileges' in cmd
        assert '--clean' in cmd and '--if-exists' in cmd
        assert '--host' in cmd and '127.0.0.1' in cmd
        assert cmd[-1] == cmd[cmd.index('-f') + 1]
        assert not os.path.exists(cmd[-1])

        assert os.environ['PGPASSWORD'] == 'secret'
        assert os.environ['PGUSER'] == 'admin'
        assert os.environ['PGDATABASE'] == 'salesdb'

    def test_manual_prefix_skips_retention_cleanup(self, backup_env, pg_env, monkeypatch):
        self._install_params(monkeypatch)
        monkeypatch.setattr(BackupService, 'MAX_BACKUPS', 1)
        stale = _make_backup(
            backup_env, 'auto_backup_20250101_000001.sql.gz', '20250101_000001')
        runner, _ = self._fake_run('SELECT 1;')
        monkeypatch.setattr(subprocess, 'run', runner)

        metadata = BackupService.create_backup(manual=True, description='pre-restore')

        assert metadata['filename'].startswith('manual_backup_')
        assert metadata['manual'] is True
        assert stale.exists()

    def test_auto_backup_triggers_retention_rotation(self, backup_env, pg_env, monkeypatch):
        self._install_params(monkeypatch)
        monkeypatch.setattr(BackupService, 'MAX_BACKUPS', 1)
        stale = _make_backup(
            backup_env, 'auto_backup_20250101_000001.sql.gz', '20250101_000001')
        runner, _ = self._fake_run('SELECT 2;')
        monkeypatch.setattr(subprocess, 'run', runner)

        metadata = BackupService.create_backup(manual=False)

        assert metadata is not None
        assert not stale.exists()
        assert len(BackupService.list_backups(auto_only=True)) == 1

    def test_non_postgres_database_returns_none_without_files(
        self, backup_env, pg_env, monkeypatch
    ):
        monkeypatch.setattr(
            BackupService, '_parse_postgres_params', staticmethod(lambda: None))
        assert BackupService.create_backup() is None
        assert list(backup_env.glob('*')) == []

    def test_pg_dump_failure_cleans_up(self, backup_env, pg_env, monkeypatch):
        self._install_params(monkeypatch)
        runner, calls = self._fake_run('', returncode=2)
        monkeypatch.setattr(subprocess, 'run', runner)

        assert BackupService.create_backup() is None
        assert list(backup_env.glob('*.sql.gz')) == []
        assert list(backup_env.glob('*.meta.json')) == []
        assert not os.path.exists(calls[0][-1])

    def test_pg_dump_missing_binary_returns_none(self, backup_env, pg_env, monkeypatch):
        self._install_params(monkeypatch)
        runner, _ = self._fake_run('', raise_fnf=True)
        monkeypatch.setattr(subprocess, 'run', runner)

        assert BackupService.create_backup(manual=True) is None
        assert list(backup_env.glob('*.sql.gz')) == []

    def test_compression_error_cleans_partial_output(self, backup_env, pg_env, monkeypatch):
        self._install_params(monkeypatch)

        def _raise(*args, **kwargs):
            raise OSError('gzip exploded')

        monkeypatch.setattr(gzip, 'open', _raise)
        runner, _ = self._fake_run('SELECT 3;')
        monkeypatch.setattr(subprocess, 'run', runner)

        assert BackupService.create_backup() is None
        assert list(backup_env.glob('*.sql.gz')) == []


class TestRestoreBackup:
    @staticmethod
    def _install_params(monkeypatch, host='127.0.0.1', port='5432'):
        params = {
            'host': host, 'port': port, 'username': 'restorer',
            'password': 'pw123', 'dbname': 'salesdb',
        }
        monkeypatch.setattr(BackupService, '_parse_postgres_params', staticmethod(lambda: params))
        monkeypatch.setattr(
            BackupService, 'create_backup',
            staticmethod(lambda *a, **k: {'filename': 'pre_restore_guard.sql.gz'}))
        return params

    def test_missing_backup_refused(self, backup_env):
        assert BackupService.restore_backup('ghost.sql.gz') is False

    def test_restore_refused_without_db_params(self, backup_env, monkeypatch):
        target = backup_env / 'auto_backup_20250101_000001.sql.gz'
        _write_gz(target)
        monkeypatch.setattr(BackupService, '_parse_postgres_params', staticmethod(lambda: None))
        assert BackupService.restore_backup(target.name) is False

    def test_sql_gz_success_pipes_to_psql_stdin(self, backup_env, monkeypatch):
        params = self._install_params(monkeypatch)
        monkeypatch.delenv('PSQL_PATH', raising=False)
        target = backup_env / 'auto_backup_20250101_000001.sql.gz'
        _write_gz(target, b'RESTORE ME;')

        popen_calls = []

        def fake_popen(cmd, **kwargs):
            proc = _FakePopenProc(returncode=0, stdin=kwargs.get('stdin'))
            popen_calls.append({'cmd': list(cmd), 'proc': proc})
            return proc

        monkeypatch.setattr(subprocess, 'Popen', fake_popen)

        assert BackupService.restore_backup(target.name) is True

        dsn = 'postgresql://{}:{}@{}:{}/{}'.format(
            params['username'], params['password'], params['host'],
            params['port'], params['dbname'])
        assert popen_calls[0]['cmd'][0] == 'psql'
        assert popen_calls[0]['cmd'][1:3] == ['--dbname', dsn]
        assert popen_calls[0]['cmd'][-2:] == ['--set', 'ON_ERROR_STOP=on']
        assert popen_calls[0]['proc'].stdout == b'RESTORE ME;'

    def test_sql_gz_failure_returns_false(self, backup_env, monkeypatch):
        self._install_params(monkeypatch)
        target = backup_env / 'auto_backup_20250102_000002.sql.gz'
        _write_gz(target)

        monkeypatch.setattr(subprocess, 'Popen', lambda cmd, **kw: _FakePopenProc(returncode=1))

        assert BackupService.restore_backup(target.name) is False

    def test_plain_sql_restored_via_open_stream(self, backup_env, monkeypatch):
        self._install_params(monkeypatch)
        target = backup_env / 'manual_backup_20250103_000003.sql'
        target.write_bytes(b'BARE SQL;')

        popen_calls = []

        def fake_popen(cmd, **kwargs):
            proc = _FakePopenProc(returncode=0, stdin=kwargs.get('stdin'))
            popen_calls.append(proc)
            return proc

        monkeypatch.setattr(subprocess, 'Popen', fake_popen)

        assert BackupService.restore_backup(target.name) is True
        assert popen_calls[0].stdout == b'BARE SQL;'

    def test_dump_format_success_via_pg_restore_temp_copy(self, backup_env, monkeypatch):
        self._install_params(monkeypatch)
        target = backup_env / 'custom.dump'
        target.write_bytes(b'PGDMP-fake')

        run_calls = []

        def fake_run(cmd, **kwargs):
            run_calls.append(list(cmd))
            return _FakeCompleted(returncode=0)

        monkeypatch.setenv('PG_RESTORE_PATH', 'custom_pg_restore.exe')
        monkeypatch.setattr(subprocess, 'run', fake_run)

        assert BackupService.restore_backup(target.name) is True

        cmd = run_calls[0]
        assert cmd[0] == 'custom_pg_restore.exe'
        assert '--clean' in cmd and '--if-exists' in cmd
        temp_used = cmd[-1]
        assert os.path.dirname(temp_used) != str(target)
        assert not os.path.exists(temp_used)

    def test_dump_format_failure_cleans_temp_and_returns_false(self, backup_env, monkeypatch):
        self._install_params(monkeypatch)
        target = backup_env / 'broken.dump'
        target.write_bytes(b'PGDMP-bad')

        run_calls = []

        def fake_run(cmd, **kwargs):
            run_calls.append(list(cmd))
            return _FakeCompleted(returncode=3, stderr='pg_restore: error')

        monkeypatch.setattr(subprocess, 'run', fake_run)

        assert BackupService.restore_backup(target.name) is False
        assert not os.path.exists(run_calls[0][-1])


class TestTriggerBackupEntrypoint:
    class _FakeApp:
        def app_context(self):
            return contextlib.nullcontext()

    def test_module_import_sets_pg_dump_env_var(self):
        assert os.environ.get('PG_DUMP_PATH') == r'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe'

    def test_main_success_reports_backup_and_json(self, capsys, monkeypatch):
        monkeypatch.setattr(trigger_backup, 'create_app', lambda: self._FakeApp())
        monkeypatch.setattr(
            BackupService, 'create_backup',
            staticmethod(lambda *a, **k: {
                'filename': 'manual_backup_x.sql.gz',
                'path': r'C:\backups\manual_backup_x.sql.gz',
                'size_mb': 1.25,
            }))
        monkeypatch.setattr(trigger_backup, 'export_db_to_json', lambda: r'C:\export\db.json')

        trigger_backup.main()

        out = capsys.readouterr().out
        assert 'SQL Backup created successfully: manual_backup_x.sql.gz' in out
        assert 'manual_backup_x.sql.gz' in out
        assert '1.25 MB' in out
        assert 'JSON Export created successfully' in out

    def test_main_backup_failure_prints_error_and_continues_to_json(self, capsys, monkeypatch):
        monkeypatch.setattr(trigger_backup, 'create_app', lambda: self._FakeApp())
        monkeypatch.setattr(BackupService, 'create_backup', staticmethod(lambda *a, **k: None))
        monkeypatch.setattr(trigger_backup, 'export_db_to_json', lambda: 'out.json')

        trigger_backup.main()

        out = capsys.readouterr().out
        assert 'SQL Backup failed. Check logs.' in out
        assert 'JSON Export created successfully: out.json' in out

    def test_main_backup_exception_caught_and_json_still_runs(self, capsys, monkeypatch):
        monkeypatch.setattr(trigger_backup, 'create_app', lambda: self._FakeApp())

        def _boom(*a, **k):
            raise RuntimeError('dump exploded')

        monkeypatch.setattr(BackupService, 'create_backup', staticmethod(_boom))
        monkeypatch.setattr(trigger_backup, 'export_db_to_json', lambda: 'ok.json')

        trigger_backup.main()

        out = capsys.readouterr().out
        assert 'Error during SQL backup: dump exploded' in out
        assert 'JSON Export created successfully: ok.json' in out

    def test_main_json_export_exception_caught(self, capsys, monkeypatch):
        monkeypatch.setattr(trigger_backup, 'create_app', lambda: self._FakeApp())
        monkeypatch.setattr(
            BackupService, 'create_backup',
            staticmethod(lambda *a, **k: {'filename': 'f', 'path': 'p', 'size_mb': 0.1}))

        def _json_boom():
            raise IOError('disk full')

        monkeypatch.setattr(trigger_backup, 'export_db_to_json', _json_boom)

        trigger_backup.main()

        out = capsys.readouterr().out
        assert 'Error during JSON export: disk full' in out
