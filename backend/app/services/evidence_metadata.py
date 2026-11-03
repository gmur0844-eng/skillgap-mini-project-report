"""
Evidence metadata: document-role policy, disciplines, source descriptions and upload formats -- all read from data
files (data/metadata/*.json) so a new role, discipline or source is configuration, never code.

  document_roles()          the role policy (required / recommended fields per role)
  validate_metadata(...)    missing required fields for a role (empty when valid)
  disciplines()             every discipline the system has seen (manifest + published runs + application DB);
                            the list only helps typing -- any other discipline is accepted
  sources()                 the Source Registry with type, scope, access method, licence/provenance and whether the
                            source is configured (never the credential itself)
  upload_formats()          the job-posting file formats the uploader parses, described as file formats: choosing
                            one never implies the application can access or scrape the platform the export came from
"""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROLES_FILE = REPO / "data/metadata/document_roles.json"
MANIFEST = REPO / "data/metadata/curriculum_sources.json"
REGISTRY = REPO / "data/metadata/source_registry.json"
GOLD = REPO / "data/gold/knowledge"

ACCESS_LABELS = {
    "LOCAL_MANIFEST": "Files registered in the project manifest (hash-verified)",
    "DROP_FOLDER": "Files a person places in a folder, each with a licence/provenance sidecar",
    "CREDENTIALED_API": "Provider API; needs the owner's key and acceptance of the provider's terms",
    "MANUAL_REQUEST": "Downloaded by a person from the official site; the source URL is kept",
}


def _json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def document_roles():
    return _json(ROLES_FILE, {"roles": [], "fields": {}})


def role_policy(role):
    return next((r for r in document_roles()["roles"] if r["role"] == role), None)


def validate_metadata(role, values):
    """Missing required fields for `role` (strings are stripped). Unknown role -> ['document_role']."""
    policy = role_policy(role)
    if policy is None:
        return ["document_role"]
    return [f for f in policy["required"] if not str(values.get(f) or "").strip()]


def disciplines(session=None):
    seen = {}

    def add(name, where):
        n = " ".join(str(name or "").split())
        if n:
            seen.setdefault(n.lower(), {"name": n, "seen_in": set()})["seen_in"].add(where)

    for d in (_json(MANIFEST, {}) or {}).get("documents", []):
        add(d.get("discipline"), "source manifest")
    latest = (_json(GOLD / "latest_run.json", {}) or {}).get("run_id")
    if latest:
        for d in ((_json(GOLD / latest / "run_report.json", {}) or {}).get("documents") or []):
            add(d.get("discipline"), f"run {latest}")
    if session is not None:
        try:
            from app.models.curriculum import Discipline
            for row in session.query(Discipline).all():
                add(row.name, "application database")
        except Exception:  # noqa: BLE001 -- the list is a typing aid; the database is optional here
            pass
    return sorted(({"name": v["name"], "seen_in": sorted(v["seen_in"])} for v in seen.values()), key=lambda x: x["name"].lower())


def sources():
    reg = _json(REGISTRY, {"sources": []}) or {"sources": []}
    out = []
    for s in reg.get("sources", []):
        env = s.get("credential_env")
        configured = (bool(os.environ.get(env)) if env else True) and bool(s.get("enabled"))
        out.append({
            "source_id": s.get("source_id"), "source_type": s.get("source_type"),
            "geographic_scope": s.get("geographic_scope"), "temporal_scope": s.get("temporal_scope"),
            "access_method": s.get("access_method"), "access_description": ACCESS_LABELS.get(s.get("access_method"), s.get("access_method")),
            "licence": s.get("license"), "provenance_policy": s.get("provenance_policy"),
            "enabled": bool(s.get("enabled")),
            "configuration_status": ("CONFIGURED" if configured else
                                     "NOT_CONFIGURED" if s.get("enabled") else "DISABLED"),
            "note": s.get("note"),
            "automatic_collection": s.get("access_method") == "CREDENTIALED_API" and configured,
        })
    return {"sources": out, "note": "Listing a source never means the application may collect from it: automatic "
                                    "collection happens only through a configured, licensed connector."}


def upload_formats():
    try:
        from app.pipelines.ingestion.job_postings import COLUMN_MAP_PRESETS
    except ImportError:  # the file-only Knowledge API has no ingestion component
        return {"formats": [], "requires": [], "reason": "uploads are handled by the full application (app.main)"}
    names = {"naukri": "Export with Naukri-style columns", "linkedin": "Export with LinkedIn-style columns",
             "fixture": "Test fixture (development only)"}
    out = []
    for key, cols in COLUMN_MAP_PRESETS.items():
        out.append({"preset": key, "label": names.get(key, key),
                    "kind": "TEST_FIXTURE" if key == "fixture" else "FILE_FORMAT",
                    "columns": sorted(v for v in cols.values() if isinstance(v, str)) if isinstance(cols, dict) else None,
                    "description": ("Column layout of a CSV file you supply. The application reads the file you upload; "
                                    "it does not connect to, log in to or scrape the platform the export came from.")})
    return {"formats": out, "requires": ["source_name", "licence_note"],
            "note": "You must be permitted to use the file. State where it came from and its licence or terms."}
