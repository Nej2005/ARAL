"""quiz answer keys

Revision ID: 7b1e2c9a5f30
Revises: 4334840c8344
Create Date: 2026-10-12 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '7b1e2c9a5f30'
down_revision = '4334840c8344'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('source_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('answer_key', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('source_items', schema=None) as batch_op:
        batch_op.drop_column('answer_key')
