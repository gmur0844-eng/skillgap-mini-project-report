"""
Seeds the disciplines reference table with illustrative examples. This is
DATA, not business logic -- no analytics module reads this list or assumes
these are the only valid disciplines; a new discipline can be added at any
time with a single INSERT, with zero code changes required anywhere else.

Usage:
    python scripts/seed/seed_disciplines.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import Base, engine, SessionLocal  # noqa: E402
from app.models.curriculum import Discipline  # noqa: E402
import app.models  # noqa: E402,F401

DISCIPLINES = [
    ("Computing & Data", "Computer science, IT, AI & data science, software engineering, and related computing programmes."),
    ("Electronics & Electrical", "Electronics, electrical, EEE, VLSI, embedded systems, and related programmes."),
    ("Mechanical & Manufacturing", "Mechanical engineering, mechatronics, automobile, manufacturing, and related programmes."),
    ("Civil & Infrastructure", "Civil engineering and infrastructure-related programmes."),
    ("Chemical & Process", "Chemical engineering and process-engineering programmes."),
    ("Life Sciences", "Biotechnology and related life-science engineering programmes."),
    ("Other Engineering", "Any engineering programme not yet categorized under a more specific discipline above."),
]


def main():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        created, skipped = 0, 0
        for name, description in DISCIPLINES:
            existing = session.query(Discipline).filter(Discipline.name == name).one_or_none()
            if existing:
                skipped += 1
                continue
            session.add(Discipline(name=name, description=description))
            created += 1
        session.commit()
        print(f"Disciplines seeded: {created} created, {skipped} already existed.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
