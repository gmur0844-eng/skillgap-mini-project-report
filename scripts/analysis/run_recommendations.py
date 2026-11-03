"""
CLI wrapper around app.analytics.run_recommendation_generation.run_recommendation_generation.

Requires that skill gap classification has already been run
(scripts/analysis/run_gap_classification.py). Uses the latest successful
skill_gap_classification run automatically if none is specified.

Usage:
    python scripts/analysis/run_recommendations.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.analytics.run_recommendation_generation import run_recommendation_generation  # noqa: E402
import app.models  # noqa: E402,F401


def main():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        result = run_recommendation_generation(session)
        print("CURRICULUM RECOMMENDATIONS")
        print(f"  analysis_run_id={result['analysis_run_id']}")
        print(f"  recommendations_created={result['recommendations_created']}")
        if "quality_metrics" in result:
            print(f"  quality_metrics={result['quality_metrics']}")
        if "note" in result:
            print(f"  note={result['note']}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
