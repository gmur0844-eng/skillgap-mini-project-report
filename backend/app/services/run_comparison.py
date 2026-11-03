"""
What differs between two analysis runs, separated into the three kinds of change the results can come from:

  curriculum         the curriculum documents analysed (by role and content hash)
  industry evidence  the job-posting and taxonomy files (their combined hash and the posting files)
  method             parser, analysis code, configuration, semantic layer, similarity backend, pipeline version,
                     discipline profile and analysis scope

A change in results is attributable to the curriculum alone only when evidence and method are the same; the
attribution says so in words. Only stored run files are read (run_report.json, industry/industry_health.json,
industry/population_scope.json); nothing is recomputed.
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GOLD = REPO / "data/gold/knowledge"
RUN_ID = re.compile(r"[0-9a-f]{16}")

METHOD_FIELDS = (
    ("pipeline", "pipeline_version", "pipeline version"),
    ("parser", "parser_fingerprint", "curriculum parser"),
    ("code", "code_fingerprint", "analysis code"),
    ("config", "config_hash", "analysis configuration"),
    ("semantic", "semantic_identity", "semantic layer"),
)


def _read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_run(run_id, gold=None):
    """The stored facts of a run, or None (unknown id or no report)."""
    if not RUN_ID.fullmatch(str(run_id or "")):
        return None
    d = Path(gold or GOLD) / run_id
    report = _read(d / "run_report.json")
    if not isinstance(report, dict):
        return None
    health = _read(d / "industry/industry_health.json", {}) or {}
    scope = _read(d / "industry/population_scope.json", {}) or {}
    target = next((x for x in report.get("documents") or [] if x.get("role") == "TARGET"), None)
    return {
        "run_id": run_id,
        "generated_at": report.get("generated_at"),
        "target": {k: (target or {}).get(k) for k in ("doc_id", "institution", "programme", "curriculum_version")}
        if target else None,
        "documents": [{k: x.get(k) for k in ("doc_id", "role", "sha256", "institution", "programme", "curriculum_version")}
                      for x in report.get("documents") or []],
        "industry_inputs_key": health.get("inputs_key"),
        "posting_files": sorted(str(f.get("source_file") if isinstance(f, dict) else f)
                                for f in (scope.get("source_files") or [])),
        "method": {**{key: report.get(field) for key, field, _ in METHOD_FIELDS},
                   "backend": (report.get("backend_resolution") or {}).get("used"),
                   "discipline_profile": (report.get("discipline_profile") or {}).get("id"),
                   "analysis_scope": report.get("analysis_scope")},
    }


def _documents(a, b):
    by_role = {}
    for side, run in (("a", a), ("b", b)):
        for d in run["documents"]:
            by_role.setdefault(d["role"], {"a": [], "b": []})[side].append(d)
    out = []
    for role in sorted(by_role):
        da = {d["sha256"]: d for d in by_role[role]["a"]}
        db = {d["sha256"]: d for d in by_role[role]["b"]}
        for sha in sorted(set(da) | set(db)):
            if sha in da and sha in db:
                status = "SAME"
            elif sha in db:
                status = "ADDED"
            else:
                status = "REMOVED"
            d = db.get(sha) or da.get(sha)
            out.append({"role": role, "status": status, "doc_id": d["doc_id"], "institution": d.get("institution"),
                        "programme": d.get("programme"), "curriculum_version": d.get("curriculum_version")})
    return out


def compare(run_a, run_b, gold=None):
    """(comparison, error). error is UNKNOWN_RUN with the id when a run is not stored."""
    a, b = load_run(run_a, gold), load_run(run_b, gold)
    if a is None:
        return None, ("UNKNOWN_RUN", run_a)
    if b is None:
        return None, ("UNKNOWN_RUN", run_b)
    docs = _documents(a, b)
    analysed = [d for d in docs if d["role"] in ("TARGET", "PREVIOUS_VERSION") and d["status"] != "SAME"]
    compared = [d for d in docs if d["role"] in ("PEER", "REFERENCE") and d["status"] != "SAME"]
    industry_changed = a["industry_inputs_key"] != b["industry_inputs_key"]
    labels = {key: label for key, _, label in METHOD_FIELDS}
    labels.update(backend="similarity backend", discipline_profile="discipline profile", analysis_scope="analysis scope")
    method = [{"component": k, "label": labels[k], "a": a["method"][k], "b": b["method"][k]}
              for k in a["method"] if a["method"][k] != b["method"][k]]
    attribution = []
    if not (analysed or compared or industry_changed or method):
        attribution.append("The two runs used the same curricula, the same industry evidence and the same method; "
                           "their results should be identical.")
    else:
        if analysed:
            attribution.append("The analysed curriculum differs: " + "; ".join(
                f"{d['role'].replace('_', ' ').lower()} {d['doc_id']} {d['status'].lower()}" for d in analysed) + ".")
        if compared:
            attribution.append("The comparison curricula differ (peers or reference): "
                               + ", ".join(f"{d['doc_id']} {d['status'].lower()}" for d in compared) + ".")
        if industry_changed:
            files_a, files_b = set(a["posting_files"]), set(b["posting_files"])
            attribution.append("The industry evidence differs (job-posting or taxonomy files)"
                               + (f": {len(files_b - files_a)} posting file(s) added, {len(files_a - files_b)} removed"
                                  if files_a or files_b else "") + ".")
        if method and not (analysed or compared or industry_changed):
            attribution.append("The curricula and the industry evidence are the same, so any difference in results "
                               "comes from the method (" + ", ".join(m["label"] for m in method) + ").")
        elif method:
            attribution.append("The method differs (" + ", ".join(m["label"] for m in method) + "), so differences "
                               "in results are not only changes in the curriculum or in industry demand. To isolate a "
                               "curriculum change, analyse both curricula with the same method and evidence.")
        elif analysed and not industry_changed:
            attribution.append("Evidence and method are the same, so differences in results come from the curriculum.")
        elif industry_changed and not analysed:
            attribution.append("The curriculum and method are the same, so differences in demand and gaps come from "
                               "the industry evidence.")
    return {
        "a": {k: a[k] for k in ("run_id", "generated_at", "target")},
        "b": {k: b[k] for k in ("run_id", "generated_at", "target")},
        "curriculum": {"changed": bool(analysed), "comparison_curricula_changed": bool(compared), "documents": docs},
        "industry_evidence": {"changed": industry_changed, "inputs_key": {"a": a["industry_inputs_key"],
                                                                          "b": b["industry_inputs_key"]},
                              "posting_files_added": sorted(set(b["posting_files"]) - set(a["posting_files"])),
                              "posting_files_removed": sorted(set(a["posting_files"]) - set(b["posting_files"]))},
        "method": {"changed": bool(method), "differences": method},
        "attribution": attribution,
    }, None
