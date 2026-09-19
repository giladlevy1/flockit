"""organization public url

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-19 20:39:09.038976
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('organization', sa.Column('public_url', sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column('organization', 'public_url')
