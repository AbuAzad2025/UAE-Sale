"""Wave-1 CLI coverage: cli_commands.py (executed) + init_dev.py (static only).

SAFETY REPORT — init_dev.py is NOT executed by this file, for these reasons:
1. Module-level code pins production defaults, including
   DATABASE_URL='postgresql://postgres:123@localhost:5432/uae_sale_dev'.
   Importing it in the test process would mutate os.environ (FLASK_ENV,
   DEBUG, OWNER_PASSWORD defaults) and point any subsequently-created app
   at a production Postgres database, which is off-limits for unit tests.
2. main() applies Alembic migrations to head and seeds owner/roles via
   ensure_system_integrity() — a mutating, network/DB-bound bootstrap that
   must never run under sqlite-memory pytest.
Instead init_dev.py is covered by static AST/source assertions below
(structure + prod-DB marker), with zero imports and zero side effects.
"""
import ast
import os

import pytest


def _read_init_dev():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, '..', '..', 'init_dev.py')
    with open(os.path.normpath(path), encoding='utf-8') as fh:
        return fh.read()


class TestCliCommands:
    def test_register_adds_commands(self, app, db):
        from cli_commands import register_cli_commands
        register_cli_commands(app)
        assert 'db-status' in app.cli.commands
        assert 'init-db' in app.cli.commands

    def test_db_status_runs_on_sqlite(self, app, db):
        from cli_commands import register_cli_commands
        register_cli_commands(app)
        runner = app.test_cli_runner()
        result = runner.invoke(args=['db-status'])
        assert result.exit_code == 0, result.output
        assert 'Heads:' in result.output
        assert 'Status:' in result.output

    def test_init_db_refuses_nonempty_db(self, app, db):
        from cli_commands import register_cli_commands
        register_cli_commands(app)
        runner = app.test_cli_runner()
        result = runner.invoke(args=['init-db'])
        assert result.exit_code != 0
        assert 'refusing to run init-db' in result.output


class TestInitDevStatic:
    """Static-only coverage of init_dev.py (never imported, never executed)."""

    def test_structure(self):
        source = _read_init_dev()
        tree = ast.parse(source)
        funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert {'main', '_run_migrations', '_seed_minimal_runtime'} <= funcs

    def test_main_guards_and_flow(self):
        source = _read_init_dev()
        assert "if __name__ == '__main__':" in source
        assert 'command.upgrade' in source
        assert 'ensure_system_integrity' in source
        assert 'create_app' in source

    def test_production_db_marker_why_not_executed(self):
        # Proves the skip reason: default target is a production Postgres URL.
        source = _read_init_dev()
        assert 'postgresql://postgres:123@localhost:5432/uae_sale_dev' in source
        assert 'ALEMBIC_RUNNING' in source
