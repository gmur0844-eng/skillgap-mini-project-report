#!/usr/bin/env python3
"""
Integrity check of a release zip (standard library only; reads the zip, changes nothing).

  python3 scripts/audit/package_integrity.py <release.zip> [--release <run_id>] [--out <report.json>]

Checks: contents listing; no secrets (key/token patterns, private keys) and no credential files; no prohibited raw
data (peer curriculum PDFs, raw job-board postings, BRONZE/SILVER text); the expected documentation, form script and
integrity artifacts are present; the packaged latest_run.json names the release; no two paths collide on a
case-insensitive file system; SHA-256 of the zip. Exit code 1 on any failure.
"""
import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

SECRET_PATTERNS = {
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "private_key_block": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "openai_style_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}"),
    "anthropic_key": re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "google_api_key": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}"),
    "slack_token": re.compile(rb"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    "assigned_secret": re.compile(rb"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password)\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{16,}['\"]"),
    "dsn_with_password": re.compile(rb"postgres(?:ql)?(?:\+\w+)?://[^:\s/'\"]+:[^@\s/'\"]{3,}@"),
}
CREDENTIAL_FILES = re.compile(r"(?i)(^|/)(\.env(\..+)?|\.pgpass|\.netrc|id_rsa|id_ed25519|credentials(\.json)?|.*\.pem|.*\.p12|.*\.key)$")
PROHIBITED = {
    "peer curriculum PDFs": re.compile(r"(?i)data/raw/curricula/(peers|incoming)/.+"),
    # every raw job file: the job spreadsheets carry recruiters' and applicants' personal details
    "raw job-board postings": re.compile(r"(?i)(data/raw/jobs/.+|jobboard_[^/]+\.csv$)"),
    "uploaded curricula (runtime state)": re.compile(r"(?i)data/(raw/curricula/(uploads|\d+)|metadata/(staged_uploads|analysis_contexts))/.+"),
    "live semantic cache (machine-local)": re.compile(r"data/cache/semantic_decisions/live/.+"),
    "extracted reference builds": re.compile(r"artifacts/rc/reference/.+"),
    "BRONZE/SILVER derived text": re.compile(r"^[^/]+/data/(bronze|silver)/.+"),
    "virtual environments / caches": re.compile(r"(/\.venv/|/__pycache__/|/node_modules/|/\.dart_tool/)"),
}
EXPECTED = ["README.md", "docs/FINAL_RELEASE_REPORT.md", "docs/FINAL_HARDENING_REPORT.md",
            "docs/DATA_EXPANSION_AUDIT.md", "docs/SEMANTIC_HUMAN_VALIDATION_FORM.md",
            "scripts/evaluation/create_semantic_validation_form.gs", "scripts/evaluation/semantic_validation.py",
            "data/evaluation/semantic_gold/computer-science-and-engineering/v1/form/form_integrity_report.json",
            "data/evaluation/semantic_gold/computer-science-and-engineering/v1/form/response_mapping.json",
            "data/evaluation/semantic_benchmark_v1/benchmark.json", "data/evaluation/full_consistency_audit.json",
            "data/evaluation/release_gap_qa_{run}.json", "data/gold/knowledge/latest_run.json",
            "data/gold/knowledge/{run}/run_report.json", "data/gold/knowledge/lineage/{run}.json",
            "artifacts/db/skillgap_knowledge_final_{run}.dump", "backend/app/main.py", "backend/requirements.txt",
            "flutter_app/pubspec.yaml", "flutter_app/lib/main.dart", "scripts/mac/final_hardening_validation.sh",
            "scripts/mac/rc_validation.sh", "scripts/audit/reproducibility_gate.py",
            "scripts/audit/reproducibility_policy.json", "artifacts/rc/validation.log",
            "artifacts/rc/reproducibility_gate.json", "docs/performance/PERFORMANCE_AUDIT.md",
            "scripts/mac/acquire_official_evidence.sh", "data/metadata/curriculum_sources.json",
            "data/metadata/official_sources.json"]
TEMPLATE = re.compile(r"(?i)\.(example|sample|template)$")


def local_default(dsn: bytes) -> bool:
    m = re.search(rb"://([^:\s/'\"]+):([^@\s'\"]+)@", dsn)
    return bool(m) and (m.group(1) == m.group(2) or m.group(2).startswith(b"${"))


TEXT_EXT = {".py", ".dart", ".md", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".txt", ".sh",
            ".gs", ".js", ".sql", ".csv", ".env", ".html"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--release", default="c066b227857f9eaf")
    ap.add_argument("--out")
    a = ap.parse_args()
    path = Path(a.zip)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    zf = zipfile.ZipFile(path)
    names = [n for n in zf.namelist() if not n.endswith("/")]
    root = Counter(n.split("/", 1)[0] for n in names).most_common(1)[0][0]
    rel = {n: n.split("/", 1)[1] if "/" in n else n for n in names}
    failures, report = [], {"zip": str(path), "sha256": sha, "bytes": path.stat().st_size, "files": len(names),
                            "root": root}
    report["top_level"] = dict(Counter(r.split("/", 1)[0] for r in rel.values()).most_common())
    # secrets
    hits, reviewed = [], []
    for n in names:
        if Path(n).suffix.lower() not in TEXT_EXT and not Path(n).name.startswith(".env"):
            continue
        if zf.getinfo(n).file_size > 50_000_000:
            continue
        data = zf.read(n)
        for kind, pat in SECRET_PATTERNS.items():
            for m in pat.finditer(data):
                hit = {"file": rel[n], "kind": kind, "match": m.group(0)[:12].decode("latin-1") + "…"}
                if kind == "dsn_with_password" and local_default(m.group(0)):
                    reviewed.append(hit | {"reason": "local development default (user = password, or ${VAR:-default})"})
                else:
                    hits.append(hit)
    report["secret_hits"] = hits
    report["reviewed_local_defaults"] = reviewed
    if hits:
        failures.append(f"{len(hits)} possible secrets")
    templates = [rel[n] for n in names if TEMPLATE.search(rel[n])]
    report["credential_templates"] = templates   # scanned above like every other text file
    creds = [rel[n] for n in names if CREDENTIAL_FILES.search(rel[n]) and not TEMPLATE.search(rel[n])]
    report["credential_files"] = creds
    if creds:
        failures.append(f"credential files: {creds[:5]}")
    # prohibited material
    prohibited = {k: [rel[n] for n in names if p.search(n)] for k, p in PROHIBITED.items()}
    report["prohibited"] = {k: v[:20] for k, v in prohibited.items()}
    for k, v in prohibited.items():
        if v:
            failures.append(f"{k}: {len(v)} files")
    # expected documentation and artifacts
    present = set(rel.values())
    missing = [e.format(run=a.release) for e in EXPECTED if e.format(run=a.release) not in present]
    report["expected_missing"] = missing
    if missing:
        failures.append(f"missing expected files: {missing}")
    # release id
    latest = f"{root}/data/gold/knowledge/latest_run.json"
    run_id = json.loads(zf.read(latest)).get("run_id") if latest in names else None
    report["packaged_release"] = run_id
    if run_id != a.release:
        failures.append(f"latest_run.json names {run_id}, expected {a.release}")
    gold_runs = sorted({r.split("/")[3] for r in rel.values() if r.startswith("data/gold/knowledge/")
                        and re.fullmatch(r"[0-9a-f]{16}", r.split("/")[3] if r.count("/") >= 4 else "")})
    report["gold_runs"] = gold_runs
    # case-insensitive collisions (files and directories)
    seen = defaultdict(set)
    for n in names:
        parts = n.split("/")
        for i in range(1, len(parts) + 1):
            p = "/".join(parts[:i])
            seen[p.lower()].add(p)
    clashes = sorted(sorted(v) for v in seen.values() if len(v) > 1)
    report["case_collisions"] = clashes
    if clashes:
        failures.append(f"case collisions: {clashes[:5]}")
    docs = [r for r in rel.values() if r.startswith("docs/")]
    report["docs"] = len(docs)
    report["failures"] = failures
    report["passed"] = not failures
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("zip", "sha256", "bytes", "files", "packaged_release", "gold_runs",
                                             "docs", "case_collisions", "credential_files", "failures", "passed")},
                     indent=1))
    print("secret hits:", len(hits), "| prohibited:", {k: len(v) for k, v in prohibited.items()})
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
