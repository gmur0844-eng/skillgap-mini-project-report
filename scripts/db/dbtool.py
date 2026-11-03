"""
PostgreSQL backup / restore / integrity for the knowledge store.

  python3 scripts/db/dbtool.py backup   --db skillgap_knowledge --out backups/x.dump
  python3 scripts/db/dbtool.py restore  --dump backups/x.dump --db skillgap_restore_test     (refuses an existing DB)
  python3 scripts/db/dbtool.py verify   --db skillgap_restore_test                          (integrity checks)
  python3 scripts/db/dbtool.py roundtrip --db skillgap_knowledge                            (backup -> fresh DB ->
                                                                                            restore -> compare -> drop)
Connection: --local (run the client tools as the `postgres` OS user, as in the dev container) or the standard libpq
environment (PGHOST, PGPORT, PGUSER, PGPASSWORD) -- credentials are never passed on the command line or logged.
The source database is only ever read; restore never overwrites an existing database.
"""
import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine.db_publish import IMPROVEMENT_PROBE_SQL, integrity_sql  # noqa: E402

ROW_COUNTS_SQL = ("SELECT json_object_agg(table_name, n) FROM (SELECT c.relname AS table_name, "
                  "(xpath('/row/n/text()', query_to_xml(format('select count(*) as n from %I.%I', n.nspname, c.relname),"
                  " false, true, '')))[1]::text::bigint AS n FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                  "WHERE c.relkind = 'r' AND n.nspname = 'knowledge') t")


def run(args, local, check=True, capture=True):
    cmd = ["su", "postgres", "-c", " ".join(shlex.quote(a) for a in args)] if local else args
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"{args[0]} failed: {r.stderr.strip()[:500]}")
    return r


def exists(db, local):
    r = run(["psql", "-d", "postgres", "-tAc", f"SELECT 1 FROM pg_database WHERE datname = '{db}'"], local)
    return r.stdout.strip() == "1"


def sql_json(db, sql, local):
    r = run(["psql", "-d", db, "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql], local)
    return json.loads(r.stdout.strip() or "null")


def backup(db, out, local):
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if local:
        tmp = Path("/tmp") / out.name
        run(["pg_dump", "-Fc", "-d", db, "-f", str(tmp)], local)
        out.write_bytes(tmp.read_bytes())
        run(["rm", "-f", str(tmp)], local)
    else:
        run(["pg_dump", "-Fc", "-d", db, "-f", str(out)], local)
    return {"db": db, "dump": str(out), "bytes": out.stat().st_size}


def restore(dump, db, local):
    if exists(db, local):
        raise SystemExit(f"refusing to restore into existing database {db!r}")
    run(["createdb", db], local)
    src = str(Path(dump).resolve())
    if local:
        tmp = f"/tmp/restore_{int(time.time())}.dump"
        Path(tmp).write_bytes(Path(src).read_bytes())
        subprocess.run(["chmod", "644", tmp])
        src = tmp
    run(["pg_restore", "--no-owner", "-d", db, src], local)
    return {"db": db, "restored_from": dump}


def verify(db, local):
    # a database published before migration 0003 has no improvement tables: verify it with the base checks
    improved = bool(sql_json(db, IMPROVEMENT_PROBE_SQL, local))
    integrity = sql_json(db, integrity_sql(improved).strip().rstrip(";"), local)
    violations = {k: v for k, v in integrity.items() if k != "row_counts" and v}
    return {"db": db, "status": "PASS" if not violations else "FAIL", "violations": violations,
            "improvement_schema": improved,
            "row_counts": sql_json(db, ROW_COUNTS_SQL, local)}


def roundtrip(db, local, workdir):
    target = f"{db}_restore_test_{int(time.time())}"
    b = backup(db, Path(workdir) / f"{db}.dump", local)
    before = sql_json(db, ROW_COUNTS_SQL, local)
    try:
        restore(b["dump"], target, local)
        after = verify(target, local)
    finally:
        run(["dropdb", "--if-exists", target], local, check=False)
    same = before == after["row_counts"]
    return {"source_db": db, "backup_bytes": b["bytes"], "tables": len(before or {}),
            "rows": sum((before or {}).values()), "row_counts_identical": same, "restored_integrity": after["status"],
            "violations": after["violations"], "status": "PASS" if same and after["status"] == "PASS" else "FAIL"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["backup", "restore", "verify", "roundtrip"])
    ap.add_argument("--db", required=True)
    ap.add_argument("--out")
    ap.add_argument("--dump")
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--workdir", default=str(ROOT / "artifacts/db_backups"))
    ap.add_argument("--report")
    a = ap.parse_args()
    res = {"backup": lambda: backup(a.db, a.out, a.local), "restore": lambda: restore(a.dump, a.db, a.local),
           "verify": lambda: verify(a.db, a.local), "roundtrip": lambda: roundtrip(a.db, a.local, a.workdir)}[a.cmd]()
    print(json.dumps(res, indent=1))
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(json.dumps(res, indent=1))
    sys.exit(0 if res.get("status", "PASS") == "PASS" else 1)
