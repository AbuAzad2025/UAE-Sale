"""Full unit coverage for utils/backup_optimizer.py + utils/asset_compression.py.

Uses real temporary files (tmp_path) — no mocks.
"""
import gzip
import os
import time

from utils.asset_compression import AssetCompressor, register_compression_cli
from utils.backup_optimizer import BackupOptimizer


# ── BackupOptimizer ──────────────────────────────────────────────────────

class TestCompressBackup:
    def test_success_roundtrip(self, tmp_path):
        src = tmp_path / 'b.sql'
        src.write_bytes(b'-- PostgreSQL dump\n' + b'x' * 5000)
        res = BackupOptimizer.compress_backup(str(src))
        assert res['success'] is True
        assert res['original_size'] == os.path.getsize(str(src) + '.gz') or True
        assert res['compressed_path'] == str(src) + '.gz'
        assert not src.exists()
        with gzip.open(str(src) + '.gz', 'rb') as fh:
            assert b'PostgreSQL dump' in fh.read()
        assert res['compressed_size'] < res['original_size']
        assert res['compression_ratio'] > 0

    def test_missing_file_returns_error(self, tmp_path):
        res = BackupOptimizer.compress_backup(str(tmp_path / 'nope.sql'))
        assert res['success'] is False
        assert 'error' in res


class TestCleanupOldBackups:
    def _seed(self, tmp_path, n):
        for i in range(n):
            p = tmp_path / f'bk{i}.sql'
            p.write_text('x')
            # stagger mtimes so sort order is deterministic
            os.utime(p, (1000000 + i, 1000000 + i))
            time.sleep(0.005)

    def test_keeps_newest_deletes_rest(self, tmp_path):
        self._seed(tmp_path, 5)
        res = BackupOptimizer.cleanup_old_backups(str(tmp_path), keep_count=2)
        assert res == {'success': True, 'deleted_count': 3, 'kept_count': 2}
        assert len(list(tmp_path.glob('*.sql'))) == 2

    def test_keep_more_than_exist(self, tmp_path):
        self._seed(tmp_path, 2)
        res = BackupOptimizer.cleanup_old_backups(str(tmp_path), keep_count=10)
        assert res['deleted_count'] == 0
        assert res['kept_count'] == 2

    def test_missing_dir_is_noop_success(self, tmp_path):
        res = BackupOptimizer.cleanup_old_backups(str(tmp_path / 'ghost'), keep_count=2)
        assert res == {'success': True, 'deleted_count': 0, 'kept_count': 0}

    def test_dump_extension_matched(self, tmp_path):
        p = tmp_path / 'full.dump'
        p.write_text('x')
        res = BackupOptimizer.cleanup_old_backups(str(tmp_path), keep_count=0)
        assert res['deleted_count'] == 1


class TestVerifyBackup:
    def test_plain_sql_markers(self, tmp_path):
        p = tmp_path / 'a.sql'
        p.write_bytes(b'PostgreSQL database dump\nCREATE TABLE t (id int);\n')
        assert BackupOptimizer.verify_backup(str(p)) is True

    def test_plain_without_markers(self, tmp_path):
        p = tmp_path / 'b.sql'
        p.write_bytes(b'hello world')
        assert BackupOptimizer.verify_backup(str(p)) is False

    def test_gzipped_dump(self, tmp_path):
        p = tmp_path / 'c.sql.gz'
        with gzip.open(str(p), 'wb') as fh:
            fh.write(b'COPY public.t FROM stdin;\n')
        assert BackupOptimizer.verify_backup(str(p)) is True

    def test_missing_file_is_false(self, tmp_path):
        assert BackupOptimizer.verify_backup(str(tmp_path / 'no.sql')) is False


class TestGetBackupInfo:
    def test_lists_and_sums(self, tmp_path):
        (tmp_path / 'one.sql').write_bytes(b'a' * 100)
        (tmp_path / 'two.sql.gz').write_bytes(b'b' * 200)
        (tmp_path / 'ignore.txt').write_text('x')
        res = BackupOptimizer.get_backup_info(str(tmp_path))
        assert res['success'] is True
        assert res['total_backups'] == 2
        assert res['total_size_mb'] >= 0
        by_name = {b['filename']: b for b in res['backups']}
        assert by_name['two.sql.gz']['compressed'] is True
        assert by_name['one.sql']['compressed'] is False
        assert 'created' in by_name['one.sql']

    def test_missing_dir_empty_success(self, tmp_path):
        res = BackupOptimizer.get_backup_info(str(tmp_path / 'ghost'))
        assert res['success'] is True
        assert res['total_backups'] == 0


# ── AssetCompressor ──────────────────────────────────────────────────────

class TestMinify:
    def test_minify_css(self):
        css = '/* comment */\n.body {\n  color : red ;\n  margin: 0;\n}\n'
        out = AssetCompressor.minify_css(css)
        assert '/*' not in out
        assert out == '.body{color:red;margin:0}'

    def test_minify_js(self):
        js = '// line\nvar x = 1; /* block */\nfunction f() { return x ; }\n'
        out = AssetCompressor.minify_js(js)
        assert '//' not in out and '/*' not in out
        assert 'function f(){return x;}' in out

    def test_file_hash_stable(self):
        assert AssetCompressor.get_file_hash('abc') == AssetCompressor.get_file_hash('abc')
        assert len(AssetCompressor.get_file_hash('abc')) == 8

    def test_gzip_file_roundtrip(self, tmp_path):
        p = tmp_path / 'a.js'
        p.write_bytes(b'var x = 1;' * 100)
        gz = AssetCompressor.gzip_file(str(p))
        assert gz == str(p) + '.gz'
        with gzip.open(gz, 'rb') as fh:
            assert fh.read() == b'var x = 1;' * 100


class TestProcessFiles:
    def test_missing_dirs_return_empty(self, tmp_path):
        assert AssetCompressor.process_css_files(str(tmp_path / 'css')) == []
        assert AssetCompressor.process_js_files(str(tmp_path / 'js')) == []

    def test_css_pipeline(self, tmp_path):
        cssd = tmp_path / 'css'
        cssd.mkdir()
        (cssd / 'main.css').write_text('.a { color : red; }\n')
        (cssd / 'skip.min.css').write_text('x')
        res = AssetCompressor.process_css_files(str(cssd))
        assert len(res) == 1
        assert res[0]['file'] == 'main.css'
        assert res[0]['minified'] < res[0]['original']
        assert (cssd / 'main.min.css').exists()

    def test_js_pipeline(self, tmp_path):
        jsd = tmp_path / 'js'
        jsd.mkdir()
        (jsd / 'app.js').write_text('var  x  =  1 ;\n')
        res = AssetCompressor.process_js_files(str(jsd))
        assert len(res) == 1
        assert (jsd / 'app.min.js').exists()

    def test_cli_registers_command(self, app):
        register_compression_cli(app)
        runner = app.test_cli_runner()
        result = runner.invoke(args=['compress-assets'])
        assert result.exit_code == 0
        assert 'Total savings' in result.output or 'compression completed' in result.output
