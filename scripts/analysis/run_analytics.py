"""
CLI wrapper around app.analytics.run_analysis. Requires that job postings and
curriculum have already been ingested AND that skill extraction
(scripts/extraction/extract_skills.py) has already been run -- this stage
only aggregates existing ExtractedSkill evidence into GOLD tables, it does
not extract anything new itself.

Each run creates a fresh, independently-timestamped AnalysisRun and GOLD rows
(see app.analytics.run_selection for why re-running is safe: results are
versioned snapshots, and every consumer reads via the LATEST successful run,
never a blind scan of all historical GOLD rows).

Usage:
    # Run everything in the correct dependency order
    python scripts/analysis/run_analytics.py --all

    # Or run stages individually
    python scripts/analysis/run_analytics.py --stage demand
    python scripts/analysis/run_analytics.py --stage coverage
    python scripts/analysis/run_analytics.py --stage alignment
    python scripts/analysis/run_analytics.py --stage tfidf
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.models.analysis import AnalysisRun  # noqa: E402
from app.analytics.run_analysis import (  # noqa: E402
    run_industry_demand_analysis,
    run_curriculum_coverage_analysis,
    run_skill_alignment_analysis,
    run_course_tfidf_alignment,
)
from app.analytics.run_selection import select_latest_successful_run  # noqa: E402
import app.models  # noqa: E402,F401


def _find_latest_run_id(session, dataset_name: str):
    runs = session.query(AnalysisRun).filter(AnalysisRun.dataset_name == dataset_name).all()
    run_dicts = [{"id": r.id, "dataset_name": r.dataset_name, "status": r.status, "started_at": r.started_at} for r in runs]
    selected = select_latest_successful_run(run_dicts, dataset_name)
    return selected["id"] if selected else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Run demand, coverage, alignment, and TF-IDF in order")
    parser.add_argument("--stage", choices=["demand", "coverage", "alignment", "tfidf"], default=None)
    args = parser.parse_args()

    if not args.all and not args.stage:
        print("Specify --all or --stage <demand|coverage|alignment|tfidf>", file=sys.stderr)
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        demand_run_id = coverage_run_id = None

        if args.all or args.stage == "demand":
            demand_result = run_industry_demand_analysis(session)
            demand_run_id = demand_result["analysis_run_id"]
            print("INDUSTRY DEMAND:", demand_result)

        if args.all or args.stage == "coverage":
            coverage_result = run_curriculum_coverage_analysis(session)
            coverage_run_id = coverage_result["analysis_run_id"]
            print("CURRICULUM COVERAGE:", coverage_result)

        if args.all or args.stage == "alignment":
            # If this invocation didn't just compute demand/coverage, fall
            # back to the latest prior successful run of each (same
            # tested logic the API uses -- see app.analytics.run_selection).
            if demand_run_id is None:
                demand_run_id = _find_latest_run_id(session, "industry_demand")
            if coverage_run_id is None:
                coverage_run_id = _find_latest_run_id(session, "curriculum_coverage")

            if demand_run_id is None or coverage_run_id is None:
                print(
                    "ERROR: --stage alignment requires a prior successful demand run AND coverage "
                    "run to exist. Run --all, or run --stage demand and --stage coverage first.",
                    file=sys.stderr,
                )
                sys.exit(1)
            alignment_result = run_skill_alignment_analysis(session, demand_run_id, coverage_run_id)
            print("SKILL ALIGNMENT:", alignment_result)

        if args.all or args.stage == "tfidf":
            tfidf_result = run_course_tfidf_alignment(session)
            print("TF-IDF ALIGNMENT:", tfidf_result)
    finally:
        session.close()


if __name__ == "__main__":
    main()
