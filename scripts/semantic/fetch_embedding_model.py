"""
Download the one approved sentence-embedding model and record its provenance.

    python scripts/semantic/fetch_embedding_model.py            # sentence-transformers/all-MiniLM-L6-v2

Writes data/models/embedding/<name>/ and PROVENANCE.json in it: repo id, the resolved revision (commit), the licence
declared by the model card, the sha256 of every file, the date and the installed library versions. The engine uses the
model only when PROVENANCE.json is present (semantic_backend._probe_sentence_transformer), and a run that uses it
records the revision and file hashes in its identity. The licence must be on the allow-list, otherwise nothing is
registered. Re-running with the same revision changes nothing.

Approved 2026-10-21 (docs/TRANSFORMER_STRATEGY.md §8, items 1 and 2). It does not change the default backend.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_REPO_ID = "sentence-transformers/all-MiniLM-L6-v2"
ALLOWED_LICENCES = {"apache-2.0", "mit", "bsd-3-clause"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def version(pkg):
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    ap.add_argument("--revision", default="main", help="branch, tag or commit; the resolved commit is recorded")
    ap.add_argument("--dest", default=None)
    args = ap.parse_args(argv)
    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        sys.exit("huggingface_hub is not installed: pip install -r backend/requirements-embedding.txt")
    info = HfApi().model_info(args.repo_id, revision=args.revision)
    licence = (getattr(info, "card_data", None) or {}).get("license") if getattr(info, "card_data", None) else None
    licence = licence or next((t.split(":", 1)[1] for t in (info.tags or []) if t.startswith("license:")), None)
    if (licence or "").lower() not in ALLOWED_LICENCES:
        sys.exit(f"licence {licence!r} of {args.repo_id} is not on the allow-list {sorted(ALLOWED_LICENCES)}; "
                 "nothing was downloaded")
    dest = Path(args.dest) if args.dest else REPO / "data/models/embedding" / args.repo_id.split("/")[-1]
    # PyTorch weights in safetensors only; no ONNX/OpenVINO/TF/Flax copies
    snapshot_download(args.repo_id, revision=info.sha, local_dir=dest,
                      ignore_patterns=["*.onnx", "onnx/*", "openvino/*", "*.h5", "*.msgpack", "*.ot",
                                       "pytorch_model.bin", "rust_model.ot", "tf_model.h5", "*.tflite"])
    files = sorted(p for p in dest.rglob("*") if p.is_file() and ".cache" not in p.parts and p.name != "PROVENANCE.json")
    prov = {
        "repo_id": args.repo_id, "revision": info.sha, "licence": licence,
        "source_url": f"https://huggingface.co/{args.repo_id}/tree/{info.sha}",
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files_sha256": {str(p.relative_to(dest)): sha256(p) for p in files},
        "total_bytes": sum(p.stat().st_size for p in files),
        "libraries": {k: version(k) for k in ("sentence-transformers", "transformers", "torch", "huggingface_hub")},
        "approval": "docs/TRANSFORMER_STRATEGY.md §8 items 1-2, approved by the project owner 2026-10-21",
        "use": "optional backend 'sentence_transformer'; never the default",
    }
    (dest / "PROVENANCE.json").write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    print(f"{args.repo_id} @ {info.sha[:12]} ({licence}), {len(files)} files, {prov['total_bytes'] / 1e6:.1f} MB -> {dest}")


if __name__ == "__main__":
    main()
