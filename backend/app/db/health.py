"""Database health for the full app: connectivity, whether the latest GOLD run is published, migration state."""
from pathlib import Path

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def migration_head():
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    except Exception:  # noqa: BLE001 -- alembic missing or misconfigured is reported, not raised
        return None


def db_check(latest_run_id=None):
    from sqlalchemy import text

    from app.db.session import engine
    out = {"ok": False, "dialect": engine.dialect.name}
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        out["ok"] = True
        try:
            out["migration_revision"] = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:  # noqa: BLE001
            conn.rollback()
            out["migration_revision"] = None
        out["migration_head"] = migration_head()
        out["migrations_current"] = bool(out["migration_head"]) and out["migration_revision"] == out["migration_head"]
        if engine.dialect.name == "postgresql" and latest_run_id:
            try:
                out["latest_run_published"] = bool(conn.execute(
                    text("SELECT 1 FROM knowledge.pipeline_run WHERE run_id = :r"), {"r": latest_run_id}).scalar())
            except Exception:  # noqa: BLE001
                conn.rollback()
                out["latest_run_published"] = False
    return out
