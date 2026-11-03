"""Document role on ingested curriculum documents (application tables).

documents.document_role (nullable): what the uploaded document is for -- TARGET, PREVIOUS_VERSION, PEER, REFERENCE or
GENERAL_REFERENCE (data/metadata/document_roles.json). Revision 0001 creates tables from the current models, so on a
fresh database the column already exists; this revision adds it only where it is missing.

Revision ID: 0005_document_role
Revises: 0004_consistency_schema
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_document_role"
down_revision = "0004_consistency_schema"
branch_labels = None
depends_on = None


def _has_column(table, column):
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names() and column in {c["name"] for c in insp.get_columns(table)}


def upgrade():
    if not _has_column("documents", "document_role"):
        op.add_column("documents", sa.Column("document_role", sa.String(length=32), nullable=True))


def downgrade():
    if _has_column("documents", "document_role"):
        op.drop_column("documents", "document_role")
