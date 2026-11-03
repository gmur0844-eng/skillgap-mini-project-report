"""Backup -> fresh database -> restore -> integrity + identical row counts, against the local PostgreSQL (skipped when
none is running). The source database is only read; the restore target is created and dropped by the test."""
import json
import shutil
import subprocess
import sys
import tempfile
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_backup_restore_roundtrip_preserves_every_row_and_integrity():
    if os.geteuid() != 0 or not shutil.which("pg_dump") or subprocess.run(
            ["su", "postgres", "-c", "psql -tAc \"select 1 from pg_database where datname='skillgap_knowledge'\""],
            capture_output=True, text=True).stdout.strip() != "1":
        raise unittest.SkipTest("no local PostgreSQL with the knowledge database")
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, str(ROOT / "scripts/db/dbtool.py"), "roundtrip", "--db", "skillgap_knowledge",
                            "--local", "--workdir", d], capture_output=True, text=True)
    res = json.loads(r.stdout)
    assert r.returncode == 0 and res["status"] == "PASS" and res["row_counts_identical"] and res["rows"] > 0


def test_restore_refuses_to_overwrite_an_existing_database():
    if os.geteuid() != 0 or not shutil.which("pg_restore") or subprocess.run(["su", "postgres", "-c", "psql -tAc 'select 1'"],
                                                        capture_output=True).returncode != 0:
        raise unittest.SkipTest("no local PostgreSQL")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/db/dbtool.py"), "restore", "--db", "postgres", "--dump",
                        "/nonexistent.dump", "--local"], capture_output=True, text=True)
    assert r.returncode != 0 and "refusing to restore into existing database" in (r.stdout + r.stderr)
