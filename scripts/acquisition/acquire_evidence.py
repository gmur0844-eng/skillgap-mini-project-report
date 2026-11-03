"""
Evidence acquisition run (explicit, never part of a reproducible pipeline run).

  python3 scripts/acquisition/acquire_evidence.py            # attempt every enabled source, report, record state
  python3 scripts/acquisition/acquire_evidence.py --register # also register validated drop-folder files in the manifest

For each enabled source (priority order) the connector validates what it can reach: files need a licence/provenance
sidecar (<file>.source.json) or they are quarantined; credentialed APIs need their key and terms. Registered files
are ingested by the next pipeline run through the normal quality gates -- this script never writes GOLD.
Every attempt (success or failure, with its reason) is recorded in data/metadata/source_registry_state.json.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import acquisition as acq  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--manifest", default=str(ROOT / "data/metadata/curriculum_sources.json"))
    a = ap.parse_args()
    manifest_path = Path(a.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    before = json.dumps(manifest, sort_keys=True)
    registry = acq.load_registry(ROOT)
    report = []
    for s in sorted(registry["sources"], key=lambda s: (s["priority"], s["source_id"])):
        conn = acq.CONNECTORS.get(s["connector"])
        print(f"[ACQUIRING] {s['source_id']} via {s['connector']}")
        if not s.get("enabled"):
            res = {"status": "SOURCE_UNAVAILABLE", "reason": "disabled in the source registry"}
        elif conn is None:
            res = {"status": "ACQUISITION_FAILED", "reason": f"no connector {s['connector']!r}"}
        else:
            try:
                res = conn.acquire(s, ROOT, manifest, register=a.register)
            except Exception as e:  # noqa: BLE001 -- recorded, never fatal
                res = {"status": "ACQUISITION_FAILED", "reason": f"{type(e).__name__}: {e}"}
        acq.record_attempt(ROOT, s["source_id"], res)
        report.append({"source_id": s["source_id"], **res})
        print(f"  -> {res['status']}: {res.get('reason')}")
    if a.register and json.dumps(manifest, sort_keys=True) != before:
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("manifest updated: rerun scripts/pipeline/run_knowledge_pipeline.py to ingest the new sources")
    out = ROOT / "artifacts/acquisition_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
