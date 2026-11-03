"""
Static generalization audit: finds subject-, discipline- or institution-
specific string literals in EXECUTABLE backend code.

Docstrings and comments are excluded (they legitimately use examples).
Every hit is classified:
  - CONDITIONAL : the literal is compared against something (==, !=, in, is)
                  -> forbidden branch logic unless it lives in test code
  - LITERAL     : the literal appears elsewhere in executable code
                  (e.g. a default argument, a dict key) -> reported for review

Usage:  python scripts/evaluation/static_generalization_audit.py [--json]
Exit code 1 if any CONDITIONAL hit exists in backend/app or scripts.
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = [ROOT / "backend" / "app", ROOT / "scripts"]

# Subject / discipline / institution identifiers that must never drive code
# paths. This list is the AUDIT's search vocabulary, not application logic.
TERMS = [
    r"operating system", r"deadlock", r"\bdbms\b", r"database management", r"\balgorithms?\b",
    r"\bsearching\b", r"computer science", r"\bcse\b", r"\bece\b", r"\beee\b", r"mechanical",
    r"\bcivil\b", r"ai ?& ?ds", r"data science", r"\bcbit\b", r"\baicte\b", r"\biit\b",
    r"chaitanya", r"thermodynamic", r"calculus", r"marketing",
]
TERM_RE = re.compile("|".join(TERMS), re.IGNORECASE)


def _docstring_nodes(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def audit_file(path):
    hits = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [{"file": str(path), "line": exc.lineno, "kind": "SYNTAX_ERROR", "text": str(exc)}]
    doc_ids = _docstring_nodes(tree)
    compared = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for sub in [node.left, *node.comparators]:
                for c in ast.walk(sub):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        compared.add(id(c))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
            if TERM_RE.search(node.value):
                hits.append({
                    "file": str(path.relative_to(ROOT)), "line": node.lineno,
                    "kind": "CONDITIONAL" if id(node) in compared else "LITERAL",
                    "text": node.value[:100],
                })
    return hits


def run():
    hits = []
    for base in SCAN_DIRS:
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or path.resolve() == Path(__file__).resolve():
                continue  # the audit's own search vocabulary is not application logic
            hits.extend(audit_file(path))
    return hits


if __name__ == "__main__":
    results = run()
    conditional = [h for h in results if h["kind"] == "CONDITIONAL"]
    if "--json" in sys.argv:
        print(json.dumps({"hits": results, "conditional_count": len(conditional)}, indent=2))
    else:
        for h in results:
            print(f"[{h['kind']}] {h['file']}:{h['line']}  {h['text']!r}")
        print(f"\nTOTAL literal hits: {len(results)}  CONDITIONAL (forbidden): {len(conditional)}")
    sys.exit(1 if conditional else 0)
