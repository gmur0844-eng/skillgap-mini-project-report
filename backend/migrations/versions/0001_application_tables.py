"""Application (ORM) tables -- baseline.

Creates every table registered on Base.metadata (app.models) that does not exist yet (checkfirst), so it is
safe both on an empty database and on a database that was created earlier with create_all. From this revision on,
schema changes to app.models are made as new revisions (`alembic revision --autogenerate`), and `alembic check`
verifies that the migrated schema matches the models.

Revision ID: 0001_application_tables
Revises:
"""
from alembic import op

import app.models  # noqa: F401
from app.db.session import Base

revision = "0001_application_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
