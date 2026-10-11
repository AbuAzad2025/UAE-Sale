"""Route-coverage census for the E2E matrix.

    python -m tests.e2e.route_coverage hits-*.json [--min-covered N]

Reads the JSON files produced by ``pytest --e2e-route-report=FILE`` (one list
of URL rules per CI shard), merges them, and compares the result against every
rule the application registers.

Why this is separate from the matrix shape guard
------------------------------------------------
The matrix guard proves the *scenario* matrix is the size it claims to be. It
says nothing about which endpoints those scenarios reach. A domain runner that
cycles three paths still produces 945 passing scenarios, so a suite can be
fully green while most of the application is untouched. That is exactly what
happened: 24640 passing scenarios covered about a fifth of the routes.

Only rules that a request actually reached are counted. The numbers come from
Flask's request hook, not from grepping the test sources, so a route counts as
covered only when it was genuinely exercised.
"""
import argparse
import collections
import glob
import json
import sys

# create_app() reconfigures logging and replaces sys.stdout with its own
# handler stream, which swallows anything printed after it runs. Hold the real
# one so the census is still visible.
_REAL_STDOUT = sys.stdout


def collect_hits(patterns):
    hits = set()
    for pattern in patterns:
        for path in glob.glob(pattern):
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
            hits.update(data if isinstance(data, list) else data.get('hits', []))
    return hits


def build_url_map():
    """Register every blueprint and return {module: {rule, ...}}."""
    import os
    os.environ.setdefault('APP_ENV', 'testing')
    os.environ.setdefault('SECRET_KEY', 'route-coverage-census')
    os.environ.setdefault('OWNER_PASSWORD', 'E2eOwner@1234567890123456!')
    os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from config import Config

    class _CensusConfig(Config):
        # SQLite's default pool does not accept the MySQL pool_size options
        # the production config carries, same reason E2ETestConfig overrides.
        SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        SQLALCHEMY_ENGINE_OPTIONS = {
            'connect_args': {'check_same_thread': False}}
        RATELIMIT_ENABLED = False

    app = create_app(_CensusConfig)
    modules = collections.defaultdict(set)
    for rule in app.url_map.iter_rules():
        if rule.endpoint == 'static':
            continue
        modules[rule.endpoint.split('.')[0]].add(rule.rule)
    return modules


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hits', nargs='+',
                        help='route-report JSON files (globs allowed)')
    parser.add_argument('--min-covered', type=int, default=0,
                        help='fail if fewer than this many routes are covered')
    parser.add_argument('--min-percent', type=float, default=0.0,
                        help='fail if coverage is below this percentage')
    parser.add_argument('--out', default=None,
                        help='also write the per-module table here')
    args = parser.parse_args(argv)

    hits = collect_hits(args.hits)
    modules = build_url_map()

    per = {m: (len(rules & hits), len(rules), sorted(rules - hits))
           for m, rules in modules.items()}
    total = sum(len(r) for r in modules.values())
    covered = sum(v[0] for v in per.values())
    pct = 100.0 * covered / total if total else 0.0

    lines = ['module,covered,total,missing']
    for m in sorted(per, key=lambda k: -(per[k][1] - per[k][0])):
        h, t, miss = per[m]
        if miss:
            lines.append(f'{m},{h},{t},{len(miss)}')
    lines.append(f'TOTAL,{covered},{total},{total - covered}')
    table = '\n'.join(lines)

    report = [
        '## Route coverage',
        '',
        f'**{covered}/{total} routes ({pct:.1f}%)** were exercised by real '
        'requests across the matrix shards.',
        '',
        '```',
        table,
        '```',
    ]
    out = '\n'.join(report)
    print(out, file=_REAL_STDOUT)
    sys.stderr.write(out + '\n')
    sys.stderr.flush()
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(out + '\n')

    problems = []
    if covered < args.min_covered:
        problems.append(
            f'only {covered} routes covered, floor is {args.min_covered}')
    if pct < args.min_percent:
        problems.append(f'coverage {pct:.1f}% is below {args.min_percent}%')
    if problems:
        for p in problems:
            print(f'route coverage check failed: {p}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())