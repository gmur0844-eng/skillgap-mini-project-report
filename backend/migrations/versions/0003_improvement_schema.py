"""Intelligence improvement release: PEER document role, peer benchmark, temporal trends, occupation resolution.

Applies app/db/knowledge_schema_improvement.sql (idempotent), the same file the GOLD publisher applies after the base
knowledge schema. PostgreSQL only; a recorded no-op on SQLite.

Revision ID: 0003_improvement_schema
Revises: 0002_knowledge_schema
"""
from pathlib import Path

from alembic import op

revision = "0003_improvement_schema"
down_revision = "0002_knowledge_schema"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "app" / "db" / "knowledge_schema_improvement.sql"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    cur = bind.connection.dbapi_connection.cursor()
    try:
        cur.execute(SQL.read_text(encoding="utf-8"))
    finally:
        cur.close()


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for t in ("occupation_resolution", "skill_trend", "temporal_population", "peer_relation", "peer_comparison"):
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS knowledge.{t}")
    bind.exec_driver_sql("ALTER TABLE knowledge.document DROP CONSTRAINT IF EXISTS document_role_check")
    bind.exec_driver_sql("ALTER TABLE knowledge.document ADD CONSTRAINT document_role_check "
                         "CHECK (role IN ('TARGET','PREVIOUS_VERSION','REFERENCE'))")
