"""
Evidence acquisition: Source Registry + connectors + evidence escalation.

When an analysis lacks the evidence it needs, the system (1) says exactly what is missing and the minimum required,
(2) consults the Source Registry (data/metadata/source_registry.json), (3) tries each legitimate source through its
connector in priority order, and (4) only reports INSUFFICIENT when every configured path is exhausted -- with every
attempt, its result and the next available action recorded. Nothing is ever fabricated: a connector either finds
real, licensed, provenance-carrying records or reports why it could not.

Two modes, so pipeline runs stay reproducible:
  inspect()  deterministic, offline: what each source currently offers (used by the pipeline -> GOLD
             intelligence/evidence_status.json, the API and the Flutter "Evidence Status" screen)
  acquire()  explicit, may change RAW + the manifest (scripts/acquisition/acquire_evidence.py): validates files in
             drop folders (licence/provenance sidecar required, invalid files quarantined), registers valid ones in
             the manifest with their SHA-256 so the next pipeline run ingests them through the normal
             RAW -> BRONZE -> SILVER -> HEALTH GATE -> GOLD gates, and records last_success / last_failure.

Escalation (recorded per requirement):
  L0 GOLD evidence -> L1 SILVER evidence -> L2 additional configured source -> L3 alternate configured source
  -> L4 semantic/model interpretation -> L5 optional human review -> L6 INSUFFICIENT_EVIDENCE
Statuses: AVAILABLE, VALIDATING, PARTIAL, INSUFFICIENT, SOURCE_UNAVAILABLE, LICENSE_RESTRICTED, ACQUISITION_FAILED,
REVIEW_REQUIRED. (ACQUIRING is shown by the acquisition CLI while it runs; it is never persisted.)
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SIDECAR_REQUIRED = {
    "job_postings": ("source_url", "license", "collected_on", "geographic_scope", "collected_by"),
    "curriculum": ("source_url", "license", "institution", "programme", "curriculum_version", "role", "discipline"),
    "onet": ("source_url", "license", "release"),
}
LICENSE_BLOCKLIST = ("unknown", "unclear", "not stated", "scraped", "")


def load_registry(repo):
    return json.loads((Path(repo) / "data/metadata/source_registry.json").read_text(encoding="utf-8"))


def load_state(repo):
    p = Path(repo) / "data/metadata/source_registry_state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"sources": {}}


# ------------------------------------------------------------------ connectors

class Connector:
    kind = "base"

    def inspect(self, source, repo, manifest):
        raise NotImplementedError

    def acquire(self, source, repo, manifest, register=False):
        """Default: acquisition is inspection (nothing to fetch)."""
        return self.inspect(source, repo, manifest)


class ManifestFilesConnector(Connector):
    """Sources already registered in the manifest (hash-verified by the pipeline before use)."""
    kind = "manifest_files"

    def inspect(self, source, repo, manifest):
        kind = source.get("manifest_kind")
        if kind == "job_postings":
            items = manifest.get("industry_sources", [])
        elif kind == "curriculum":
            items = manifest.get("documents", [])
        else:
            items = [t for t in manifest.get("taxonomy_sources", []) if t.get("kind") == kind]
        present = [i for i in items if (Path(repo) / i["path"]).exists()]
        return {"status": "AVAILABLE" if present else "SOURCE_UNAVAILABLE", "records": len(present),
                "reason": f"{len(present)} registered file(s) present" if present else "no registered file present"}


def _validate_sidecar(path, kind):
    side = path.with_name(path.name + ".source.json")
    if not side.exists():
        return None, "LICENSE_UNDECLARED: no <file>.source.json sidecar (licence and provenance are required)"
    try:
        meta = json.loads(side.read_text(encoding="utf-8"))
    except ValueError:
        return None, "INVALID_SIDECAR: not valid JSON"
    missing = [k for k in SIDECAR_REQUIRED.get(kind, ()) if not str(meta.get(k) or "").strip()]
    if missing:
        return None, f"INVALID_SIDECAR: missing {missing}"
    if str(meta.get("license", "")).strip().lower() in LICENSE_BLOCKLIST:
        return None, "LICENSE_RESTRICTED: licence is unclear; unclear-licence data is never used as evidence"
    if not str(meta["source_url"]).startswith(("http://", "https://")):
        return None, "INVALID_SIDECAR: source_url must be an http(s) URL"
    return meta, None


class DropFolderConnector(Connector):
    """Files a person placed in a folder, each with a licence/provenance sidecar. Unregistered valid files are
    VALIDATING until `acquire --register` adds them to the manifest; invalid files are quarantined, never used."""
    kind = "drop_folder"

    def _scan(self, source, repo):
        folder = Path(repo) / source["path"]
        exts = tuple(source.get("accepted_extensions", ()))
        files = sorted(p for p in folder.glob("*") if p.is_file() and p.suffix.lower() in exts) if folder.exists() else []
        return folder, files

    def inspect(self, source, repo, manifest):
        folder, files = self._scan(source, repo)
        registered = {Path(i["path"]).name for i in manifest.get("industry_sources", []) + manifest.get("documents", [])}
        registered_sha = {i.get("expected_sha256") for i in manifest.get("industry_sources", []) + manifest.get("documents", [])}
        pending, rejected = [], []
        for f in files:
            if f.name in registered:
                continue
            # provenance/licence first: an unlicensed file is quarantined for that reason even if its bytes match
            meta, err = _validate_sidecar(f, source.get("manifest_kind"))
            if not err and hashlib.sha256(f.read_bytes()).hexdigest() in registered_sha:
                err = "DUPLICATE_ACQUISITION: identical content (SHA-256) is already registered; not ingested twice"
            (rejected if err else pending).append({"file": f.name, **({"reason": err} if err else {})})
        if pending:
            status, reason = "VALIDATING", f"{len(pending)} new file(s) with valid provenance await registration"
        elif rejected:
            status = ("LICENSE_RESTRICTED" if any("LICENSE" in r["reason"] for r in rejected) else
                      "SOURCE_UNAVAILABLE" if all(r["reason"].startswith("DUPLICATE_ACQUISITION") for r in rejected) else
                      "ACQUISITION_FAILED")
            reason = f"{len(rejected)} file(s) quarantined (see files)"
        else:
            status, reason = "SOURCE_UNAVAILABLE", f"no new files in {source['path']}"
        return {"status": status, "records": len(pending), "reason": reason, "pending": pending, "quarantined": rejected}

    def acquire(self, source, repo, manifest, register=False):
        res = self.inspect(source, repo, manifest)
        if not register or not res["pending"]:
            return res
        folder, _ = self._scan(source, repo)
        added = []
        for item in res["pending"]:
            f = folder / item["file"]
            meta, _err = _validate_sidecar(f, source["manifest_kind"])
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            rel = str(f.relative_to(repo))
            if source["manifest_kind"] == "job_postings":
                manifest.setdefault("industry_sources", []).append({
                    "source_id": f"{f.stem}_{sha[:8]}", "kind": "job_postings", "path": rel, "expected_sha256": sha,
                    "format": f.suffix.lstrip("."), "acquisition": f"drop folder via source registry ({source['source_id']})",
                    "population_id": meta.get("population_id") or f"POPULATION:{meta.get('geographic_scope')}:{meta.get('collected_by')}",
                    "provenance": meta})
            elif source["manifest_kind"] == "curriculum":
                manifest.setdefault("documents", []).append({
                    "doc_id": meta.get("doc_id") or f"{f.stem}".lower(), "role": meta["role"],
                    "institution": meta["institution"], "programme": meta["programme"],
                    "discipline": meta["discipline"], "curriculum_version": meta["curriculum_version"],
                    "academic_year": meta.get("academic_year"), "path": rel, "expected_sha256": sha,
                    "source_url": meta["source_url"], "retrieved_at": meta.get("retrieved_at") or meta.get("collected_on"),
                    "licence_note": meta.get("license"),
                    "acquisition": f"drop folder via source registry ({source['source_id']})"})
            else:
                continue
            added.append(rel)
        return {**res, "status": "AVAILABLE" if added else res["status"], "registered": added,
                "reason": f"registered {len(added)} file(s); the next pipeline run ingests them through the quality gates"}


class CredentialedApiConnector(Connector):
    """A remote API that needs the owner's credentials and acceptance of the provider's terms."""
    kind = "credentialed_api"

    def inspect(self, source, repo, manifest):
        import os
        if not source.get("enabled"):
            return {"status": "SOURCE_UNAVAILABLE", "records": 0,
                    "reason": "disabled in the registry: " + (source.get("note") or "requires credentials and terms")}
        if not os.environ.get(source.get("credential_env") or "", ""):
            return {"status": "SOURCE_UNAVAILABLE", "records": 0,
                    "reason": f"credential {source.get('credential_env')} is not configured"}
        return {"status": "ACQUISITION_FAILED", "records": 0,
                "reason": "no client is installed for this API; add a connector class before enabling it"}


class ManualRequestConnector(Connector):
    """Evidence only a person can obtain (e.g. an official PDF behind a website). Lists what is requested."""
    kind = "manual_request"

    def inspect(self, source, repo, manifest):
        req = [r for r in manifest.get("requested_peer_sources", []) if r.get("status") != "SUPPLIED"]
        return {"status": "SOURCE_UNAVAILABLE" if req else "AVAILABLE", "records": 0,
                "reason": (f"{len(req)} requested document(s) not supplied: download the official PDF, place it in "
                           "data/raw/curricula/incoming with a .source.json sidecar") if req else "all requests supplied",
                "requested": [r.get("name") for r in req]}


CONNECTORS = {c.kind: c() for c in (ManifestFilesConnector, DropFolderConnector, CredentialedApiConnector,
                                    ManualRequestConnector)}


# ------------------------------------------------------------------ requirements + escalation

def _measure(req, facts, settings):
    m = req["measure"]
    if m == "periods_with_min_postings":
        per = facts.get("postings_by_period") or {}
        need_n = settings.get("min_eligible_postings_per_period", 30)
        valid = sorted(p for p, n in per.items() if n >= need_n)
        return len(valid), settings.get("min_periods_for_trend", 2), {"postings_by_period": per,
                                                                      "granularity": facts.get("period_granularity", "month"),
                                                                      "min_postings_per_period": need_n}
    if m == "peer_documents":
        return facts.get("peer_documents", 0), req.get("min_required", 1), {
            "reference_documents": facts.get("reference_documents"), "peer_documents": facts.get("peer_doc_ids"),
            "requested_peers_missing": facts.get("requested_peers_missing") or []}
    if m == "established_occupation_share":
        tot = facts.get("postings") or 0
        share = round((facts.get("established_postings") or 0) / tot, 4) if tot else 0.0
        return share, req.get("min_required", 0.5), {"established_postings": facts.get("established_postings"), "postings": tot}
    if m == "independent_labels":
        return facts.get("independent_labels", 0), req.get("min_required", 1), {}
    return 0, 1, {"reason": f"unknown measure {m}"}


def evaluate(repo, facts, settings, manifest, registry=None, state=None):
    """Deterministic evidence status for every registered requirement (no network, no writes)."""
    registry = registry or load_registry(repo)
    state = state or load_state(repo)
    out = []
    for req in registry["requirements"]:
        have, need, detail = _measure(req, facts, settings)
        ok = have >= need
        levels = [{"level": 0, "name": "GOLD evidence", "result": "SUFFICIENT" if ok else "INSUFFICIENT",
                   "measured": have, "required": need}]
        attempts = []
        if not ok:
            levels.append({"level": 1, "name": "SILVER evidence", "result": "NO_ADDITIONAL_EVIDENCE",
                           "note": "GOLD is built from every SILVER record of the registered sources"})
            srcs = sorted((s for s in registry["sources"] if s["source_type"] in req["source_types"]),
                          key=lambda s: (s["priority"], s["source_id"]))
            for s in srcs:
                if s["priority"] == 1:
                    continue      # already counted in L0
                conn = CONNECTORS.get(s["connector"])
                res = conn.inspect(s, repo, manifest) if conn else {"status": "ACQUISITION_FAILED",
                                                                    "reason": f"no connector {s['connector']!r}"}
                st = (state.get("sources") or {}).get(s["source_id"], {})
                attempts.append({"source_id": s["source_id"], "level": 2 if s["priority"] == 2 else 3,
                                 "access_method": s["access_method"], "license": s["license"],
                                 "status": res["status"], "reason": res["reason"],
                                 "last_success": st.get("last_success"), "last_failure": st.get("last_failure"),
                                 **{k: res[k] for k in ("pending", "quarantined", "requested") if res.get(k)}})
            for a in attempts:
                levels.append({"level": a["level"], "name": f"source {a['source_id']}", "result": a["status"]})
            levels.append({"level": 4, "name": "semantic/model interpretation", "result": "NOT_APPLICABLE",
                           "note": "a model can interpret existing evidence; it can never create missing records"})
            if req["requirement_id"] == "INDEPENDENT_SEMANTIC_LABELS":
                levels.append({"level": 5, "name": "human review", "result": "REVIEW_REQUIRED"})
            levels.append({"level": 6, "name": "INSUFFICIENT_EVIDENCE", "result": "REPORTED"})
        partial_peers = ok and req["measure"] == "peer_documents" and bool(detail.get("requested_peers_missing"))
        if partial_peers:
            status = "PARTIAL"
        elif ok:
            status = "AVAILABLE"
        elif any(a["status"] == "VALIDATING" for a in attempts):
            status = "VALIDATING"
        elif req["requirement_id"] == "INDEPENDENT_SEMANTIC_LABELS":
            status = "REVIEW_REQUIRED"
        elif have and have > 0:
            status = "PARTIAL"
        elif attempts and all(a["status"] == "LICENSE_RESTRICTED" for a in attempts):
            status = "LICENSE_RESTRICTED"
        elif attempts and all(a["status"] in ("SOURCE_UNAVAILABLE",) for a in attempts):
            status = "SOURCE_UNAVAILABLE"
        else:
            status = "INSUFFICIENT"
        out.append({"requirement_id": req["requirement_id"], "analysis": req["analysis"], "status": status,
                    "what_is_missing": (("requested peer curricula not yet supplied: " +
                                         ", ".join(detail["requested_peers_missing"])) if partial_peers else
                                        None if ok else _missing_text(req, have, need, detail)),
                    "why_it_matters": req["why_it_matters"], "measured": have, "required": need, "detail": detail,
                    "sources_attempted": attempts, "escalation": levels,
                    "last_successful_acquisition": max((a["last_success"] for a in attempts if a.get("last_success")),
                                                       default=None),
                    "next_action": (_next_action(req, attempts) if (not ok or partial_peers) else None)})
    return out


def _missing_text(req, have, need, detail):
    return {"TEMPORAL_TREND": f"{have} period(s) with enough postings; at least {need} needed",
            "PEER_BENCHMARK": f"{have} peer-institution curriculum document(s); at least {need} needed",
            "OCCUPATION_MAPPING": f"{have:.0%} of postings have an established occupation; {need:.0%} needed",
            "INDEPENDENT_SEMANTIC_LABELS": f"{have} independent label(s) on the frozen benchmark; {need} needed",
            }.get(req["requirement_id"], f"{have} of {need}")


def _next_action(req, attempts):
    pend = [a for a in attempts if a["status"] == "VALIDATING"]
    if pend:
        return "run scripts/acquisition/acquire_evidence.py --register, then rerun the pipeline"
    return {"TEMPORAL_TREND": "add job postings from another period (same population definition) to "
                              "data/raw/jobs/incoming with a .source.json sidecar, or configure a credentialed source",
            "PEER_BENCHMARK": "download the official peer curriculum PDF to data/raw/curricula/incoming with a sidecar",
            "OCCUPATION_MAPPING": "place an occupation taxonomy release (e.g. O*NET, kept as a separate scope) in "
                                  "data/raw/onet with a sidecar, or review unmapped titles",
            "INDEPENDENT_SEMANTIC_LABELS": "an independent reviewer labels the model-blind sheet produced by "
                                           "scripts/semantic/benchmark_labelling.py export"}.get(req["requirement_id"])


def record_attempt(repo, source_id, result):
    """Acquisition CLI only: persist last_success / last_failure for a source."""
    p = Path(repo) / "data/metadata/source_registry_state.json"
    state = load_state(repo)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    s = state.setdefault("sources", {}).setdefault(source_id, {})
    key = "last_success" if result["status"] in ("AVAILABLE",) else "last_failure"
    s[key] = now
    s["last_status"], s["last_reason"] = result["status"], result.get("reason")
    p.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    return state


def count_independent_labels(repo, benchmark="semantic_benchmark_v1"):
    """Labels on the frozen benchmark made by an independent (non-assistant) reviewer, ingested through
    scripts/semantic/benchmark_labelling.py. The assistant-labelled development gold never counts."""
    d = Path(repo) / "data/evaluation" / benchmark / "independent_labels"
    n = 0
    for f in sorted(d.glob("labels_*.json")) if d.exists() else []:
        doc = json.loads(f.read_text(encoding="utf-8"))
        if doc.get("independent") is True and doc.get("model_blind") is True:
            n = max(n, len([x for x in doc.get("labels", []) if x.get("label")]))
    return n
