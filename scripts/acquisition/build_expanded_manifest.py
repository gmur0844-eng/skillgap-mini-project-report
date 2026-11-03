#!/usr/bin/env python3
"""
Build the manifest of an evidence-expansion run WITHOUT touching the release manifest.

  python3 scripts/acquisition/build_expanded_manifest.py [--out data/metadata/expanded_sources.json]

Copies data/metadata/curriculum_sources.json, registers every valid drop-folder file (sidecar with licence and
provenance required; duplicates by SHA-256 refused) into the COPY through the existing acquisition connectors, and
marks requested peers whose official document is now registered as SUPPLIED. The release manifest stays as it is;
the expanded run is produced from the copy and replaces the release only if it passes the same validation and
materially improves the evidence (docs/DATA_EXPANSION_AUDIT.md).
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
    ap.add_argument("--base", default=str(ROOT / "data/metadata/curriculum_sources.json"))
    ap.add_argument("--out", default=str(ROOT / "data/metadata/expanded_sources.json"))
    a = ap.parse_args()
    manifest = json.loads(Path(a.base).read_text(encoding="utf-8"))
    registry = acq.load_registry(ROOT)
    results = []
    for s in registry["sources"]:
        if s.get("connector") != "drop_folder" or not s.get("enabled"):
            continue
        res = acq.CONNECTORS["drop_folder"].acquire(s, ROOT, manifest, register=True)
        results.append({"source_id": s["source_id"], "status": res["status"], "registered": res.get("registered", []),
                        "quarantined": res.get("quarantined", [])})
    by_doc = {d["doc_id"]: d for d in manifest.get("documents", [])}
    cfg = json.loads((ROOT / "data/metadata/official_sources.json").read_text(encoding="utf-8"))
    names = {d["doc_id"]: d["institution"] for d in cfg.get("peer_documents", [])}
    for req in manifest.get("requested_peer_sources", []):
        for doc_id, inst in names.items():
            if doc_id in by_doc and req.get("status") != "SUPPLIED" and inst.split()[-1].lower() in req["name"].lower():
                req.update(status="SUPPLIED", doc_id=doc_id)
                req.pop("reason", None)
    manifest["_expansion"] = {"base_manifest": str(Path(a.base).relative_to(ROOT)),
                              "registered": [r for res in results for r in res["registered"]],
                              "note": "derived manifest of an evidence-expansion run; the release manifest is unchanged"}
    Path(a.out).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=1))
    print(f"written {Path(a.out).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
