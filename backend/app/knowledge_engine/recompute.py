"""
Automatic recomputation after new evidence (improvement release).

When valid evidence has been acquired (a new job-posting file, a curriculum, a taxonomy release -- registered in the
manifest by the acquisition flow), the affected analytics are identified, the pipeline is rerun (a new run id --
the parent run is never overwritten) and the lineage is recorded:

  parent run -> source changes (added / removed / changed files by SHA-256, per source type)
             -> planned affected analytics (from the dependency map below)
             -> new run -> changed outputs (per GOLD file, run ids normalised so a changed run id alone is not a change)

The dependency map is declarative: a source type lists the stages that read it, directly or downstream.
Lineage records are written OUTSIDE the run directories (data/gold/knowledge/lineage/<new_run>.json) so they never
alter a run's content digest.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

DEPENDENCIES = {
    "JOB_POSTINGS": ["industry.silver", "industry.extract (skills, ESCO mapping)", "industry.demand", "industry.segments",
                     "industry_v2 (trends, dimensions, clusters)", "occupation resolution", "curriculum coverage vs demand",
                     "skill gaps v1/v2", "recommendations", "knowledge graph", "peer benchmark (industry alignment)",
                     "evidence status"],
    "CURRICULUM:TARGET": ["silver (target)", "concepts", "reference mapping", "drift", "coverage depth", "skill gaps v1/v2",
                          "recommendations", "knowledge graph", "peer benchmark", "evidence status"],
    "CURRICULUM:PREVIOUS_VERSION": ["silver (previous)", "concepts", "drift", "curriculum-industry lag", "knowledge graph"],
    "CURRICULUM:REFERENCE": ["silver (reference)", "concepts", "reference mapping", "skill gaps v1/v2", "recommendations",
                             "peer benchmark (reference comparison)"],
    "CURRICULUM:PEER": ["silver (peer)", "peer benchmark", "evidence status"],
    "SKILL_TAXONOMY": ["ESCO load", "industry.extract", "every industry and intelligence analytic"],
    "OCCUPATION_TAXONOMY": ["occupation resolution", "occupation-aware demand", "evidence status"],
    "CODE_OR_CONFIG": ["every stage whose code or configuration changed (code fingerprint / config hash)"],
}
_RUN_ID_RE = re.compile(r"\b[0-9a-f]{16}\b")


def source_inventory(manifest):
    """{key: {"sha256", "type", "path"}} for every registered source."""
    inv = {}
    for d in manifest.get("documents", []):
        inv[f"document:{d['doc_id']}"] = {"sha256": d.get("expected_sha256"), "type": f"CURRICULUM:{d['role']}", "path": d["path"]}
    for j in manifest.get("industry_sources", []):
        inv[f"industry:{j['source_id']}"] = {"sha256": j.get("expected_sha256"), "type": "JOB_POSTINGS", "path": j["path"],
                                             "population_id": j.get("population_id")}
    for t in manifest.get("taxonomy_sources", []):
        kind = "OCCUPATION_TAXONOMY" if "occupation" in str(t.get("kind", "")) or "onet" in str(t.get("kind", "")) else "SKILL_TAXONOMY"
        inv[f"taxonomy:{t['source_id']}"] = {"sha256": t.get("expected_sha256"), "type": kind, "path": t["path"]}
    return inv


def inventory_from_run(run_dir):
    """The sources a finished run actually used: curriculum documents from its run_report, job-posting files from
    its GOLD postings (source_id + source_sha256 of every accepted posting)."""
    run_dir = Path(run_dir)
    report = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))
    inv = {}
    for d in report.get("documents", []):
        inv[f"document:{d['doc_id']}"] = {"sha256": d.get("sha256"), "type": f"CURRICULUM:{d['role']}", "path": d.get("path")}
    postings = run_dir / "industry" / "postings.jsonl"
    if postings.exists():
        for line in postings.read_text(encoding="utf-8").splitlines():
            if line.strip():
                p = json.loads(line)
                inv.setdefault(f"industry:{p['source_id']}", {"sha256": p.get("source_sha256"), "type": "JOB_POSTINGS",
                                                             "path": p.get("source_file")})
    audit_path = run_dir / "industry" / "esco_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        full = audit.get("full_source") or {}
        if full.get("source_id"):
            inv[f"taxonomy:{full['source_id']}"] = {"sha256": full.get("sha256"), "type": "SKILL_TAXONOMY", "path": full.get("path")}
        delta = ((audit.get("delta_change_information") or {}).get("source") or {})
        if delta.get("source_id"):
            inv[f"taxonomy:{delta['source_id']}"] = {"sha256": delta.get("sha256"), "type": "SKILL_TAXONOMY", "path": delta.get("path")}
    return inv, report.get("code_fingerprint"), report.get("config_hash")


def source_changes(parent_inv, new_inv):
    added = sorted(k for k in new_inv if k not in parent_inv)
    removed = sorted(k for k in parent_inv if k not in new_inv)
    changed = sorted(k for k in new_inv if k in parent_inv and parent_inv[k].get("sha256") and new_inv[k].get("sha256")
                     and parent_inv[k]["sha256"] != new_inv[k]["sha256"])
    return {"added": [{"source": k, **new_inv[k]} for k in added], "removed": [{"source": k, **parent_inv[k]} for k in removed],
            "changed": [{"source": k, "from": parent_inv[k]["sha256"], "to": new_inv[k]["sha256"], "type": new_inv[k]["type"]}
                        for k in changed]}


def plan(changes, code_or_config_changed):
    types = sorted({x["type"] for part in ("added", "removed", "changed") for x in changes[part]})
    if code_or_config_changed:
        types.append("CODE_OR_CONFIG")
    affected = []
    for t in types:
        for stage in DEPENDENCIES.get(t, [f"unknown source type {t}: full rerun"]):
            if stage not in affected:
                affected.append(stage)
    return {"source_types": types, "affected_analytics": affected, "recompute": bool(types)}


# identifiers whose hash includes the run id (directly: scope, gap, peerrel; through them: rec, norec (suppression), trace, the
# knowledge-graph edge ids of edges that touch a scope node). They are replaced by their prefix and JSON-lines
# files are compared as sorted line sets, so a new run id alone never counts as a changed output.
_DERIVED_ID_RE = re.compile(r"\b(scope|gap|rec|norec|trace|peerrel|kg):[0-9a-f]{16}\b")


def _normalised_hash(path, run_ids):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return hashlib.sha256(raw).hexdigest()
    for rid in run_ids:
        text = text.replace(rid, "<RUN_ID>")
    text = _DERIVED_ID_RE.sub(lambda m: f"<{m.group(1)}>", text)
    if path.suffix == ".jsonl":
        text = "\n".join(sorted(text.splitlines()))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


EXCLUDED = ("run_report.json", "run_report.md", "observability.json", "publish_report.json")


def diff_runs(parent_dir, new_dir):
    """Per GOLD file: ADDED / REMOVED / CHANGED / UNCHANGED, with both run ids replaced by a placeholder."""
    parent_dir, new_dir = Path(parent_dir), Path(new_dir)
    ids = [parent_dir.name, new_dir.name]
    def files(d):
        return {str(p.relative_to(d)): p for p in d.rglob("*") if p.is_file() and p.name not in EXCLUDED}
    a, b = files(parent_dir), files(new_dir)
    out = {"added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)), "changed": [], "unchanged": []}
    for rel in sorted(set(a) & set(b)):
        (out["unchanged"] if _normalised_hash(a[rel], ids) == _normalised_hash(b[rel], ids) else out["changed"]).append(rel)
    out["counts"] = {k: len(v) for k, v in out.items() if isinstance(v, list)}
    return out


def lineage_record(parent_run, new_run, changes, planned, diff, parent_fp, new_fp):
    return {"parent_run": parent_run, "new_run": new_run,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "code_fingerprint": {"parent": parent_fp, "new": new_fp, "changed": parent_fp != new_fp},
            "source_changes": changes, "planned_recomputation": planned, "changed_outputs": diff,
            "note": ("run ids and identifiers derived from them (scope, gap, recommendation, suppression, peer relation, "
                     "graph edge ids) are normalised before comparison; an output that differs only by them is UNCHANGED")}


def write_lineage(repo, record):
    d = Path(repo) / "data/gold/knowledge/lineage"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{record['new_run']}.json"
    p.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return p
