"""The destructive PostgreSQL fixture must refuse non-opted-in targets."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "scheme,database,opt_in,expected",
    [
        (
            "postgresql",
            "ERP-lite",
            None,
            "Refusing destructive PostgreSQL tests against ERP-lite",
        ),
        (
            "postgresql",
            "ERP-lite",
            "1",
            "Refusing destructive PostgreSQL tests against ERP-lite",
        ),
        (
            "postgres",
            "ERP-lite",
            "1",
            "Refusing destructive PostgreSQL tests against ERP-lite",
        ),
        (
            "postgresql",
            "other_database",
            None,
            "PostgreSQL test fixtures drop schema public",
        ),
        (
            "postgresql",
            "other_database?dbname=ERP-lite",
            "1",
            "explicit, unambiguous database name",
        ),
    ],
)
def test_postgres_guard_runs_before_app_initialization(
    scheme, database, opt_in, expected
):
    env = os.environ.copy()
    # Port 1 cannot be the live development PostgreSQL instance. Collection
    # alone should not need a connection even if the guard regresses.
    env["DATABASE_URL"] = f"{scheme}://unused@127.0.0.1:1/{database}"
    if opt_in is None:
        env.pop("ALLOW_DESTRUCTIVE_POSTGRES_TESTS", None)
    else:
        env["ALLOW_DESTRUCTIVE_POSTGRES_TESTS"] = opt_in
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_maintenance_pricing.py",
            "--collect-only",
            "-q",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert expected in result.stdout + result.stderr


def test_sqlite_file_requires_explicit_opt_in():
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///do-not-create-test-fixture.db"
    env.pop("ALLOW_DESTRUCTIVE_SQLITE_TESTS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_maintenance_pricing.py",
            "--collect-only",
            "-q",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "SQLite test fixtures drop tables" in result.stdout + result.stderr
