"""
Reproducible end-to-end workflow over the real curriculum sources:

    RAW -> BRONZE -> SILVER -> HEALTH GATE -> GOLD [-> PostgreSQL]

Usage (from the repository root):
    python scripts/pipeline/run_knowledge_pipeline.py                  # run, write GOLD
    python scripts/pipeline/run_knowledge_pipeline.py --publish        # + load into local PostgreSQL
    python scripts/pipeline/run_knowledge_pipeline.py --publish --dsn postgresql://user@host/db
    python scripts/pipeline/run_knowledge_pipeline.py --record-baseline  # after reviewing a healthy run
    python scripts/pipeline/run_knowledge_pipeline.py --force-extract  # ignore the BRONZE cache
    python scripts/pipeline/run_knowledge_pipeline.py --keep-default   # a new run that does NOT become the run the
        # app opens by default (data/gold/knowledge/latest_run.json is left as it is)
    python scripts/pipeline/run_knowledge_pipeline.py --semantic-backend sentence_transformer
        # experiment with the optional local embedding model: a new run id, never made the published default

Sources come from data/metadata/curriculum_sources.json; configuration from
backend/app/knowledge_engine/engine_config.json. Exit code 2 when any
document fails the health gate (analytics for it are BLOCKED, not produced).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.knowledge_engine.pipeline import run  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest")
    parser.add_argument("--config")
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--dsn")
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--semantic-backend", choices=("tfidf", "sentence_transformer"), default=None,
                        help="override engine_config.json's semantic_backend for this run only")
    parser.add_argument("--keep-default", action="store_true",
                        help="do not make this run the app's default (latest_run.json stays as it is)")
    args = parser.parse_args()
    experiment = args.semantic_backend not in (None, "tfidf")
    if experiment and (args.publish or args.record_baseline):
        parser.error("--semantic-backend experiments are not published and do not record baselines")
    report = run(manifest_path=args.manifest, config_path=args.config, force_extract=args.force_extract,
                 publish=args.publish, dsn=args.dsn, record_baseline=args.record_baseline,
                 config_overrides={"semantic_backend": args.semantic_backend} if args.semantic_backend else None,
                 set_latest=not (experiment or args.keep_default))
    res = report.get("backend_resolution") or {}
    if experiment and res.get("used") != args.semantic_backend:
        print(f"note: {args.semantic_backend} was not available, the run used {res.get('used')}: "
              f"{res.get('fallback_reason')}", file=sys.stderr)
    print(json.dumps({k: report[k] for k in ("run_id", "content_digest", "health", "concepts", "families",
                                              "topic_mappings_by_relationship", "concept_drift", "course_drift")}, indent=2))
    print("funnel:", json.dumps(report["observability"]["funnel"]))
    if args.keep_default or experiment:
        print(f"default analysis unchanged; open this one with run_id={report['run_id']}")
    print("gates:", {k: v["status"] for k, v in report["analytics_gates"].items()})
    if "publish" in report:
        print("publish:", report["publish"]["status"], report["publish"]["inserted"])
    return 2 if "FAIL" in report["health"].values() else 0


if __name__ == "__main__":
    sys.exit(main())
