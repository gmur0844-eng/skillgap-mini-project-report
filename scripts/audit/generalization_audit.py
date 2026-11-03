#!/usr/bin/env python3
"""
Static generalization audit: does production code assume a discipline, an institution or a ranking?

  python3 scripts/audit/generalization_audit.py [--out data/evaluation/branch_generalization_audit.json]

Scans backend/app and flutter_app/lib (production code only; tests, fixtures and data are allowed to name real
examples). Every hit is classified:
  COMMENT_OR_DOCSTRING       explanatory text (e.g. which real document a rule was verified on) -- allowed
  SOURCE_SPECIFIC_CONFIG     a parser/format for a named source (file column layouts, URL id patterns) -- allowed
  PRODUCTION_CONDITIONAL     executable logic that branches on a discipline / institution -- NOT allowed
  HARDCODED_LIST             a finite list of disciplines / branches used by logic -- NOT allowed
  RANKING_LOGIC              a university score or ranking -- NOT allowed
Exit code 1 when a NOT-allowed hit exists.
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TERMS = re.compile(r"\b(CSE|ECE|EEE|AI&DS|AIDS|Computer Science|Mechanical|Civil|Electrical|Electronics|CBIT|Chaitanya|"
                   r"AICTE|IIT|NIT|Warangal|Kanpur|Naukri|naukri|LinkedIn|linkedin)\b")
RANKING = re.compile(r"(?i)\b(best_university|university_rank|rank_universit|institution_score|overall_score)\b")
SOURCE_CONFIG = {  # file -> why a named source is legitimate there
    "backend/app/pipelines/ingestion/job_postings.py": "column layout presets of supplied export files",
    "backend/app/services/evidence_metadata.py": "human-readable names of the column layout presets",
    "backend/app/knowledge_engine/jobs.py": "posting identity: URL id patterns of named job boards",
    "backend/app/api/v1/ingestion.py": "default column layout preset name",
    "flutter_app/lib/screens/ingestion_screen.dart": "column layout preset names",
}


def python_text_spans(src):
    """Line numbers that are docstrings or string-only statements (comments are handled per line)."""
    lines = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return lines
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) and isinstance(node.value.value, str):
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def classify(path, lineno, line, doc_lines):
    rel = str(path.relative_to(ROOT))
    stripped = line.strip()
    code = line.split("#", 1)[0] if path.suffix == ".py" else line.split("//", 1)[0]
    if lineno in doc_lines or stripped.startswith(("#", "//", "///", "*")) or not TERMS.search(code):
        return "COMMENT_OR_DOCSTRING"
    if rel in SOURCE_CONFIG:
        return "SOURCE_SPECIFIC_CONFIG"
    if re.search(r"\b(if|elif|case|switch|==|!=|in \()", code):
        return "PRODUCTION_CONDITIONAL"
    if re.search(r"[\[\(\{].*['\"].*['\"],\s*['\"]", code):
        return "HARDCODED_LIST"
    return "STRING_LITERAL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/evaluation/branch_generalization_audit.json"))
    a = ap.parse_args()
    files = sorted(list((ROOT / "backend/app").rglob("*.py")) + list((ROOT / "flutter_app/lib").rglob("*.dart")))
    hits, ranking = [], []
    for f in files:
        src = f.read_text(encoding="utf-8")
        doc_lines = python_text_spans(src) if f.suffix == ".py" else set()
        for i, line in enumerate(src.splitlines(), 1):
            if TERMS.search(line):
                hits.append({"file": str(f.relative_to(ROOT)), "line": i, "text": line.strip()[:160],
                             "classification": classify(f, i, line, doc_lines)})
            if RANKING.search(line.split("#", 1)[0]):
                ranking.append({"file": str(f.relative_to(ROOT)), "line": i, "text": line.strip()[:160]})
    not_allowed = [h for h in hits if h["classification"] in ("PRODUCTION_CONDITIONAL", "HARDCODED_LIST")]
    from collections import Counter
    out = {"scanned_files": len(files), "hits": len(hits), "by_classification": dict(Counter(h["classification"] for h in hits)),
           "not_allowed": not_allowed, "ranking_logic": ranking, "source_specific_config": SOURCE_CONFIG,
           "structural_checks": {
               "document_roles_from_data": (ROOT / "data/metadata/document_roles.json").exists(),
               "discipline_is_free_text": "discipline" in json.loads((ROOT / "data/metadata/document_roles.json").read_text())["fields"],
               "validation_packages_by_discipline": sorted(str(p.parent.relative_to(ROOT)) for p in
                                                           (ROOT / "data/evaluation/semantic_gold").glob("*/*/MANIFEST.json"))},
           "known_limitations": [
               "discipline identity is an exact string: two spellings of one discipline are analysed as two disciplines "
               "(the upload form offers the disciplines already seen to avoid this)",
               "the industry taxonomy loader reads ESCO; another taxonomy needs a loader (the taxonomy source is recorded "
               "per mapping and a concept can exist without any taxonomy mapping)",
               "the reference-vocabulary scope (core_reference.applies_to_discipline) is data; a discipline without one "
               "simply has no reference vocabulary"],
           "hits_detail": hits}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({k: out[k] for k in ("scanned_files", "hits", "by_classification")} |
                     {"not_allowed": len(not_allowed), "ranking_logic": len(ranking)}, indent=1))
    for h in not_allowed:
        print("NOT ALLOWED", h)
    sys.exit(1 if not_allowed or ranking else 0)


if __name__ == "__main__":
    main()
