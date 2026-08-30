"""Flask CLI commands for the UAE-Sale ERP.

Registers ``flask db ...`` and other management commands so that
the standard Alembic workflow works without manual setup.
"""
import os
import sys
import click
from flask import Flask
from flask.cli import with_appcontext


def register_cli_commands(app: Flask) -> None:
    """Attach CLI commands to *app*.

    Currently this just wires ``flask db`` (via Flask-Migrate) so the
    standard ``flask db migrate`` / ``flask db upgrade`` workflow
    works.  Other operational commands can be added here.
    """
    # Flask-Migrate auto-registers ``flask db`` when Migrate is
    # attached to both the app and the CLI.  The ``migrate`` /
    # ``upgrade`` / ``downgrade`` / ``history`` / ``heads`` /
    # ``current`` / ``stamp`` / ``show`` / ``merge`` / ``check``
    # subcommands are all provided by Flask-Migrate out of the box.
    from flask_migrate import Migrate
    from extensions import db, migrate
    # Re-attach the existing Migrate to the CLI so ``flask db`` works.
    migrations_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'migrations',
    )
    migrate.init_app(app, db, directory=migrations_dir)

    @app.cli.command('db-status')
    @with_appcontext
    def db_status():
        """Show the current migration head and which revs are applied."""
        from alembic.config import Config
        from alembic import command
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import inspect

        cfg = Config(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'migrations', 'alembic.ini'))
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        click.echo(f'Heads: {heads}')

        insp = inspect(db.engine)
        if 'alembic_version' in insp.get_table_names():
            current = script.get_current_head()
            click.echo(f'Current: {current}')
            if current in heads:
                click.echo('Status: OK (single head, fully migrated)')
            else:
                click.echo('Status: OUT OF SYNC')
        else:
            click.echo('Status: NOT MIGRATED (alembic_version table missing)')
