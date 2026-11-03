"""Consistency / hardening release: run-scoped graph edge key and the graph's mapping_kind.

Applies app/db/knowledge_schema_consistency.sql (idempotent), the same file the GOLD publisher applies after the
improvement schema. PostgreSQL only; a recorded no-op on SQLite.

Revision ID: 0004_consistency_schema
Revises: 0003_improvement_schema
"""
from pathlib import Path

from alembic import op

revision = "0004_consistency_schema"
down_revision = "0003_improvement_schema"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "app" / "db" / "knowledge_schema_consistency.sql"


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
    # The composite key is kept on downgrade: restoring the run-invariant key would have to drop the edges of every
    # run but one. Only the additive column goes.
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.exec_driver_sql("ALTER TABLE knowledge.concept_relationship DROP CONSTRAINT IF EXISTS concept_relationship_mapping_kind_check")
    bind.exec_driver_sql("ALTER TABLE knowledge.concept_relationship DROP COLUMN IF EXISTS mapping_kind")
