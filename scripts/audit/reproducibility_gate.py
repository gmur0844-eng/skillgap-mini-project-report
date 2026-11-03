#!/usr/bin/env python3
"""
Cross-machine reproducibility gate: the same code and inputs built on two machines must give the same GOLD outputs,
apart from a narrow, documented set of platform-sensitive fields (scripts/audit/reproducibility_policy.json).

  python3 scripts/audit/reproducibility_gate.py --reference <run dir> --candidate <run dir> [--out report.json]

  PASS  the runs have the same identity (run id, code, parser, config, semantic identity) and every difference is
        allowed by the policy and within its bounds. Every allowed difference is listed in the report.
  FAIL  anything else: a different identity (not a reproducibility comparison), an added or removed file, a changed
        file without a rule, a difference outside a rule's fields, or a count beyond its tolerance.

This is NOT the release comparison against the protected release (compare_runs.py --base c066...), which compares
different code and is reviewed separately. Exit code 0 on PASS, 1 on FAIL.
"""
import argparse
import fnmatch
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine.recompute import _DERIVED_ID_RE, diff_runs  # noqa: E402

IDENTITY = ("run_id", "code_fingerprint", "parser_fingerprint", "config_hash", "semantic_identity", "pipeline_version")


def _text(path, run_ids):
    text = path.read_text(encoding="utf-8")
    for rid in run_ids:
        text = text.replace(rid, "<RUN_ID>")
    return _DERIVED_ID_RE.sub(lambda m: f"<{m.group(1)}>", text)


def load(path, run_ids):
    text = _text(path, run_ids)
    if path.suffix == ".jsonl":
        return [json.loads(x) for x in text.splitlines() if x.strip()]
    return json.loads(text)


def within(ref, new, tol):
    return abs(new - ref) <= max(tol.get("abs", 0), tol.get("rel", 0) * abs(ref))


# ------------------------------------------------------------------ rule kinds
def label_fields(rule, ref, new):
    allowed, failures = [], []
    if rule.get("list_path"):
        ref_rest = {k: v for k, v in ref.items() if k != rule["list_path"]}
        new_rest = {k: v for k, v in new.items() if k != rule["list_path"]}
        if ref_rest != new_rest:
            failures.append(f"fields outside '{rule['list_path']}' differ")
        ref, new = ref[rule["list_path"]], new[rule["list_path"]]
    key, fields = rule["key"], set(rule["fields"])
    a, b = {r[key]: r for r in ref}, {r[key]: r for r in new}
    if len(a) != len(ref) or len(b) != len(new):
        failures.append(f"duplicate {key} values")
    if set(a) != set(b):
        failures.append(f"different records: {len(set(a) - set(b))} only in the reference, "
                        f"{len(set(b) - set(a))} only in the candidate")
    for k in sorted(set(a) & set(b)):
        ra, rb = a[k], b[k]
        other = {f for f in set(ra) | set(rb) if f not in fields and ra.get(f) != rb.get(f)}
        if other:
            failures.append(f"{k}: fields outside the policy differ: {sorted(other)}")
        for f in sorted(fields):
            if ra.get(f) != rb.get(f):
                allowed.append({"record": k, "field": f, "reference": ra.get(f), "candidate": rb.get(f)})
    if [r[key] for r in ref] != [r[key] for r in new] and not allowed:
        failures.append("record order differs without a label difference")
    return allowed, failures


def peer_relations(rule, ref, new):
    allowed, failures = [], []
    variable, tol = set(rule["variable_relationships"]), rule["count_tolerance"]

    def norm(r):
        return json.dumps({k: v for k, v in r.items() if k not in ("relation_uid", "run_id")}, sort_keys=True)

    fixed_a = Counter(norm(r) for r in ref if r["relationship"] not in variable)
    fixed_b = Counter(norm(r) for r in new if r["relationship"] not in variable)
    if fixed_a != fixed_b:
        rels = Counter(json.loads(x)["relationship"] for x in (fixed_a - fixed_b) + (fixed_b - fixed_a))
        failures.append(f"relations outside {sorted(variable)} differ: {dict(rels)}")
    ca = Counter((r["comparison_doc_id"], r["relationship"]) for r in ref if r["relationship"] in variable)
    cb = Counter((r["comparison_doc_id"], r["relationship"]) for r in new if r["relationship"] in variable)
    sa = {norm(r) for r in ref if r["relationship"] in variable}
    sb = {norm(r) for r in new if r["relationship"] in variable}
    changed = Counter((json.loads(x)["comparison_doc_id"], json.loads(x)["relationship"]) for x in sa ^ sb)
    churn = rule.get("churn_tolerance", 0.0)
    for k in sorted(set(ca) | set(cb)):
        if ca[k] != cb[k] or changed[k]:
            entry = {"peer": k[0], "relationship": k[1], "reference_count": ca[k], "candidate_count": cb[k],
                     "records_differing": changed[k]}
            if not within(ca[k], cb[k], tol):
                failures.append(f"{k[0]} {k[1]}: {ca[k]} -> {cb[k]} exceeds the count tolerance {tol}")
            elif changed[k] > max(tol.get("abs", 0), churn * ca[k]):
                failures.append(f"{k[0]} {k[1]}: {changed[k]} of {ca[k]} records differ, beyond the churn tolerance {churn}")
            else:
                allowed.append(entry)
    return allowed, failures


def json_paths(rule, ref, new):
    allowed, failures = [], []
    patterns = [(re.escape(a["path"]).replace(r"\[\*\]", r"\[\d+\]") + "$", a["type"]) for a in rule["allowed"]]

    def rule_for(path):
        return next((t for p, t in patterns if re.match(p, path)), None)

    def walk(x, y, path):
        kind = rule_for(path)
        if kind == "list":
            if x != y:
                xs = {json.dumps(i, sort_keys=True) for i in x or []}
                ys = {json.dumps(i, sort_keys=True) for i in y or []}
                ok = within(len(x or []), len(y or []), rule["count_tolerance"])
                entry = {"path": path, "reference_items": len(x or []), "candidate_items": len(y or []),
                         "items_only_in_reference": len(xs - ys), "items_only_in_candidate": len(ys - xs)}
                (allowed if ok else failures).append(entry if ok else f"{path}: list length beyond tolerance {entry}")
            return
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                walk(x.get(k), y.get(k), f"{path}.{k}" if path else k)
            return
        if isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            for i, (u, v) in enumerate(zip(x, y)):
                walk(u, v, f"{path}[{i}]")
            return
        if x == y:
            return
        if kind == "count" and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            ok = within(x, y, rule["count_tolerance"])
        elif kind == "pct" and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            ok = abs(y - x) <= rule["pct_tolerance"]
        else:
            failures.append(f"{path}: not allowed to differ ({json.dumps(x)[:80]} -> {json.dumps(y)[:80]})")
            return
        entry = {"path": path, "reference": x, "candidate": y}
        (allowed if ok else failures).append(entry if ok else f"{path}: {x} -> {y} exceeds tolerance")

    walk(ref, new, "")
    return allowed, failures


KINDS = {"label_fields": label_fields, "peer_relations": peer_relations, "json_paths": json_paths}


def identity(run_dir):
    rep = json.loads((Path(run_dir) / "run_report.json").read_text(encoding="utf-8"))
    return {k: rep.get(k) for k in IDENTITY}, rep.get("numeric_environment")


def gate(reference, candidate, policy):
    reference, candidate = Path(reference), Path(candidate)
    out = {"scope": policy["scope"], "policy_version": policy["version"], "reference": str(reference),
           "candidate": str(candidate), "failures": [], "allowed_differences": []}
    ref_id, ref_env = identity(reference)
    new_id, new_env = identity(candidate)
    out["identity"] = {"reference": ref_id, "candidate": new_id}
    out["numeric_environment"] = {"reference": ref_env, "candidate": new_env}
    for k in IDENTITY:
        if ref_id[k] != new_id[k]:
            out["failures"].append(f"identity: {k} differs ({ref_id[k]} vs {new_id[k]}): "
                                   "not the same code and inputs, so not a reproducibility comparison")
    d = diff_runs(reference, candidate)
    out["files"] = {k: len(d[k]) for k in ("unchanged", "changed", "added", "removed")}
    out["failures"] += [f"{f}: only in the candidate" for f in d["added"]]
    out["failures"] += [f"{f}: only in the reference" for f in d["removed"]]
    run_ids = [reference.name, candidate.name]
    rules = {r["file"]: r for r in policy["rules"]}
    for f in d["changed"]:
        rule = rules.get(f) or next((r for p, r in rules.items() if fnmatch.fnmatch(f, p)), None)
        if rule is None:
            out["failures"].append(f"{f}: changed, and no policy rule allows it")
            continue
        allowed, failures = KINDS[rule["kind"]](rule, load(reference / f, run_ids), load(candidate / f, run_ids))
        out["failures"] += [f"{f}: {x}" for x in failures]
        if allowed:
            out["allowed_differences"].append({"file": f, "rule": rule["kind"], "why": rule["why"],
                                               "differences": allowed})
        elif not failures:
            out["failures"].append(f"{f}: changed, but no difference the rule recognises (check the normalisation)")
    out["verdict"] = "FAIL" if out["failures"] else "PASS"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--policy", default=str(ROOT / "scripts/audit/reproducibility_policy.json"))
    ap.add_argument("--out")
    a = ap.parse_args()
    out = gate(a.reference, a.candidate, json.loads(Path(a.policy).read_text(encoding="utf-8")))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"reproducibility gate: {out['verdict']}  files {out['files']}")
    for g in out["allowed_differences"]:
        print(f"  allowed  {g['file']} ({g['rule']}): {len(g['differences'])} difference(s)")
        for x in g["differences"][:12]:
            print("           " + json.dumps(x, ensure_ascii=False)[:160])
        if len(g["differences"]) > 12:
            print(f"           ... {len(g['differences']) - 12} more in the report")
    for f in out["failures"]:
        print(f"  FAIL     {f}")
    sys.exit(0 if out["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
