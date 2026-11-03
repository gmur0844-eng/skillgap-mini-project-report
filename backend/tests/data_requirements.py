"""
Tests that read private, git-ignored evidence skip with a reason when it is absent (a fresh clone, CI), and run in
full on a machine that has it. The evidence itself is not redistributable (peer-institution PDFs, job postings) or is
large (analysis runs), so it is never committed; see docs/LOCAL_DEVELOPMENT.md.
"""
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GOLD = REPO / "data/gold/knowledge"


def has_published_run():
    try:
        run_id = json.loads((GOLD / "latest_run.json").read_text())["run_id"]
    except (OSError, ValueError, KeyError):
        return False
    return (GOLD / run_id / "run_report.json").exists()


def has_run(run_id):
    return (GOLD / run_id / "run_report.json").exists()


def has_replay_recording():
    from app.knowledge_engine.config import load_config
    runs = (load_config().get("semantic_replay") or {}).get("runs") or []
    return bool(runs) and all((REPO / r[k]).exists() for r in runs for k in ("cache_file", "gate_file") if r.get(k))


requires_published_run = unittest.skipUnless(
    has_published_run(), "needs a published analysis in data/gold (git-ignored evidence; not present here)")


def requires_run(run_id):
    return unittest.skipUnless(has_run(run_id), f"needs analysis run {run_id} in data/gold (git-ignored; not present)")


requires_replay_recording = unittest.skipUnless(
    has_replay_recording(), "needs the verified model recording and its gate file (data/semantic_runs is git-ignored)")
