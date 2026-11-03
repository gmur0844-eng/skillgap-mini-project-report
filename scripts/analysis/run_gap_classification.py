"""
CLI wrapper around app.analytics.run_gap_classification.run_skill_gap_classification.

Requires that industry demand and curriculum coverage have already been
computed (scripts/analysis/run_analytics.py --stage demand / --stage
coverage). Trend and drift integration are automatic if a successful
industry_skill_trends / curriculum_drift run already exists; otherwise
trend_label/drift_status are simply None for every skill.

Usage:
    python scripts/analysis/run_gap_classification.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.analytics.run_gap_classification import run_skill_gap_classification  # noqa: E402
import app.models  # noqa: E402,F401


def main():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        result = run_skill_gap_classification(session)
        print("SKILL GAP CLASSIFICATION")
        print(f"  analysis_run_id={result['analysis_run_id']}")
        print(f"  skills_classified={result['skills_classified']}")
        print(f"  source_runs={result['source_runs']}")
        print(f"  counts={result['counts']}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
