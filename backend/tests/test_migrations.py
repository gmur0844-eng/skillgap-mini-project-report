"""Alembic migration chain and the knowledge schema's idempotency. The full upgrade -> data -> upgrade -> reload
cycle against PostgreSQL runs in scripts/db/migration_cycle_test.sh (needs SQLAlchemy + Alembic)."""
import ast
import shutil
import subprocess
import sys
import os
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VERSIONS = ROOT / "migrations" / "versions"


def _revisions():
    out = {}
    for f in sorted(VERSIONS.glob("*.py")):
        tree = ast.parse(f.read_text())
        vals = {t.targets[0].id: ast.literal_eval(t.value) for t in tree.body
                if isinstance(t, ast.Assign) and isinstance(t.targets[0], ast.Name)
                and t.targets[0].id in ("revision", "down_revision")}
        out[vals["revision"]] = vals["down_revision"]
    return out


def test_migration_chain_is_linear_with_one_head():
    revs = _revisions()
    assert len(revs) >= 2
    roots = [r for r, d in revs.items() if d is None]
    assert len(roots) == 1
    children = {}
    for r, d in revs.items():
        children.setdefault(d, []).append(r)
    assert all(len(v) == 1 for v in children.values()), children
    heads = set(revs) - {d for d in revs.values() if d}
    # the improvement release adds 0003 on top of 0002 and the consistency release 0004 (knowledge) and 0005 (application: document role); the chain
    # stays linear with exactly one head
    assert heads == {"0005_document_role"}
    assert revs["0003_improvement_schema"] == "0002_knowledge_schema"
    assert revs["0004_consistency_schema"] == "0003_improvement_schema"
    assert revs["0005_document_role"] == "0004_consistency_schema"


def test_knowledge_migration_and_publisher_use_the_same_schema_file():
    from app.knowledge_engine.db_publish import SCHEMA_PATH
    src = (VERSIONS / "0002_knowledge_schema.py").read_text()
    assert '"app" / "db" / "knowledge_schema.sql"' in src
    assert SCHEMA_PATH.resolve() == (ROOT / "app/db/knowledge_schema.sql").resolve()


def test_alembic_ini_holds_no_credentials():
    ini = (ROOT / "alembic.ini").read_text()
    assert "sqlalchemy.url" not in ini and "password" not in ini.lower()


def _psql(db, sql=None, file=None):
    cmd = f"psql -v ON_ERROR_STOP=1 -q -d {db} " + (f"-f {file}" if file else f"-c \"{sql}\"")
    return subprocess.run(["su", "postgres", "-c", cmd], capture_output=True, text=True)


def test_knowledge_schema_applies_twice_on_an_empty_postgres_database():
    if os.name != "posix" or os.geteuid() != 0 or not shutil.which("psql") or subprocess.run(["su", "postgres", "-c", "psql -tAc 'select 1'"],
                                                  capture_output=True).returncode != 0:
        raise unittest.SkipTest("no local PostgreSQL server")
    db = "mig_test_" + uuid.uuid4().hex[:8]
    subprocess.run(["su", "postgres", "-c", f"createdb {db}"], check=True)
    try:
        schema = ROOT / "app/db/knowledge_schema.sql"
        for _ in range(2):
            r = _psql(db, file=schema)
            assert r.returncode == 0, r.stderr
        r = subprocess.run(["su", "postgres", "-c", f"psql -tA -d {db} -c \"select count(*) from information_schema.tables "
                            "where table_schema='knowledge'\""], capture_output=True, text=True)
        assert int(r.stdout.strip()) >= 30
    finally:
        subprocess.run(["su", "postgres", "-c", f"dropdb {db}"])
