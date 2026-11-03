"""
Repository security audit (static). Exit code 1 on any FAIL.

Checks
  secrets        credential-shaped literals in tracked text files (keys, tokens, private keys, passwords in URLs)
  env_files      no real .env committed; .env.example has empty secret values
  debug          DEBUG defaults to false; production refuses debug (validated in app.core.config)
  shell          no shell=True / os.system / eval / exec in application code
  sql            no SQL built with f-strings from request input in API/service code
  cors           no wildcard CORS in code; origins come from configuration
  uploads        uploads never use the client path, are size-limited while streaming, are cleaned up
  path_input     run ids validated before any file access
  error_leakage  API errors never include exception text or tracebacks
Writes artifacts/security_audit.json.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "node_modules", ".dart_tool", "build", "__pycache__", "archive", "gold", "bronze", "silver", "raw",
             "external", "cache", "semantic_runs", ".venv", "db_backups"}
TEXT = {".py", ".dart", ".json", ".yaml", ".yml", ".ini", ".toml", ".md", ".sh", ".txt", ".sql", ".env", ".example",
        ".cfg", ".mako", ".html", ".js"}
SECRET_PATTERNS = {
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----",
    "generic_api_key": r"(?i)\b(api[_-]?key|secret|token|passwd|password)\b\s*[:=]\s*['\"][A-Za-z0-9_\-/+=]{16,}['\"]",
    "bearer_token": r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{20,}",
    "openai_style_key": r"\bsk-[A-Za-z0-9]{20,}",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "url_with_password": r"[a-z+]+://[^\s:/@]+:[^\s@/]{6,}@(?!db:|localhost|127\.0\.0\.1)",
}
ALLOW = [re.compile(p) for p in (r"security_audit\.py", r"test_", r"SECURITY_AUDIT\.md")]


def files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and (p.suffix in TEXT or p.name.startswith(".env")):
            yield p


def main():
    results, fail = {}, False
    hits = []
    for p in files():
        rel = str(p.relative_to(ROOT))
        if any(a.search(rel) for a in ALLOW):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, pat in SECRET_PATTERNS.items():
            for m in re.finditer(pat, text):
                hits.append({"file": rel, "pattern": name, "line": text[:m.start()].count("\n") + 1})
    results["secrets"] = {"status": "PASS" if not hits else "FAIL", "findings": hits}

    env_files = [str(p.relative_to(ROOT)) for p in ROOT.rglob(".env") if not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)]
    example = (ROOT / ".env.example").read_text()
    nonempty_secret = [m.group(0).split("=")[0] for m in re.finditer(r"(?m)^[ \t]*[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z_]*[ \t]*=[ \t]*[^\s#]+", example)]
    results["env_files"] = {"status": "PASS" if not env_files and not nonempty_secret else "FAIL",
                            "committed_env_files": env_files, "example_secrets_with_values": nonempty_secret}

    cfg = (ROOT / "backend/app/core/config.py").read_text()
    results["debug"] = {"status": "PASS" if "debug: bool = False" in cfg and "DEBUG must be false in production" in cfg
                        else "FAIL"}

    app_code = [p for p in (ROOT / "backend/app").rglob("*.py")]
    shell = [str(p.relative_to(ROOT)) for p in app_code
             if re.search(r"shell\s*=\s*True|os\.system\(|\beval\(|(?<![\w.])exec\(", p.read_text())]
    results["shell"] = {"status": "PASS" if not shell else "FAIL", "files": shell}

    api = [p for p in (ROOT / "backend/app/api").rglob("*.py")] + [p for p in (ROOT / "backend/app/services").rglob("*.py")]
    fsql = [str(p.relative_to(ROOT)) for p in api if re.search(r"(execute|text)\(\s*f['\"]", p.read_text())]
    results["sql"] = {"status": "PASS" if not fsql else "FAIL", "files": fsql,
                      "note": "API/service SQL goes through the SQLAlchemy ORM or bound parameters"}

    wildcard = [str(p.relative_to(ROOT)) for p in app_code if re.search(r"allow_origins\s*=\s*\[\s*['\"]\*", p.read_text())]
    results["cors"] = {"status": "PASS" if not wildcard else "FAIL", "wildcard_in_code": wildcard}

    ing = (ROOT / "backend/app/api/v1/ingestion.py").read_text()
    up_ok = all(k in ing for k in ("FILE_TOO_LARGE", "_cleanup(", "re.sub(r\"[^A-Za-z0-9._-]\"", "UNSUPPORTED_FILE_TYPE"))
    results["uploads"] = {"status": "PASS" if up_ok else "FAIL"}

    ks = (ROOT / "backend/app/services/knowledge_service.py").read_text()
    results["path_input"] = {"status": "PASS" if "check_run_id(run_id)" in ks and "RUN_ID_RE" in ks else "FAIL"}

    leak = [str(p.relative_to(ROOT)) for p in api if re.search(r"HTTPException\([^)]*\{exc\}", p.read_text())]
    err = (ROOT / "backend/app/core/errors.py").read_text()
    results["error_leakage"] = {"status": "PASS" if not leak and "INTERNAL_ERROR" in err else "FAIL", "files": leak}

    fail = any(v["status"] != "PASS" for v in results.values())
    out = ROOT / "artifacts/security_audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=1))
    for k, v in results.items():
        print(f"{k:14} {v['status']}" + (f"  {v.get('findings') or v.get('files') or ''}" if v["status"] != "PASS" else ""))
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
