"""Knowledge-engine GOLD schema (schema `knowledge`, PostgreSQL only).

Applies app/db/knowledge_schema.sql, which is idempotent (CREATE ... IF NOT EXISTS, guarded ALTERs) and is the same
file the GOLD publisher applies, so the migrated schema and the publisher's schema can never diverge.
On SQLite this revision is a recorded no-op: the knowledge store requires PostgreSQL.

Revision ID: 0002_knowledge_schema
Revises: 0001_application_tables
"""
from pathlib import Path

from alembic import op

revision = "0002_knowledge_schema"
down_revision = "0001_application_tables"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "app" / "db" / "knowledge_schema.sql"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # executed on the raw DB-API cursor without parameters, so '%' in the SQL is never treated as a placeholder
    cur = bind.connection.dbapi_connection.cursor()
    try:
        cur.execute(SQL.read_text(encoding="utf-8"))
    finally:
        cur.close()


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("DROP SCHEMA IF EXISTS knowledge CASCADE")
