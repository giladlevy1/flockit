"""Always-on sessions: a work-in-progress snapshot, and who continues it

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Autogenerate leaves enum types to be created by hand on PostgreSQL.
continuity = postgresql.ENUM('off', 'auto', name='continuity_mode', create_type=False)


def upgrade() -> None:
    continuity.create(op.get_bind(), checkfirst=True)

    op.add_column('session', sa.Column('wip_ref', sa.String(length=200), nullable=True))
    op.add_column('session', sa.Column('wip_sha', sa.String(length=64), nullable=True))
    op.add_column('session', sa.Column('wip_pushed', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('session', sa.Column('wip_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('session', sa.Column('continued_by_run_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'session_continued_by_run_id_fkey', 'session', 'workflow_run', ['continued_by_run_id'], ['id'],
        ondelete='SET NULL', use_alter=True,
    )

    op.add_column('user', sa.Column('continuity', continuity, server_default='off', nullable=False))
    op.add_column('user', sa.Column('personal_for_id', sa.UUID(), nullable=True))
    op.create_foreign_key('user_personal_for_id_fkey', 'user', 'user', ['personal_for_id'], ['id'], ondelete='CASCADE')
    # One personal AI developer per person: the handoff must never have to choose.
    op.create_index('uq_user_personal_for', 'user', ['personal_for_id'], unique=True,
                    postgresql_where=sa.text('personal_for_id IS NOT NULL'))


def downgrade() -> None:
    op.drop_index('uq_user_personal_for', table_name='user')
    op.drop_constraint('user_personal_for_id_fkey', 'user', type_='foreignkey')
    op.drop_column('user', 'personal_for_id')
    op.drop_column('user', 'continuity')
    op.drop_constraint('session_continued_by_run_id_fkey', 'session', type_='foreignkey')
    op.drop_column('session', 'continued_by_run_id')
    op.drop_column('session', 'wip_at')
    op.drop_column('session', 'wip_pushed')
    op.drop_column('session', 'wip_sha')
    op.drop_column('session', 'wip_ref')
    continuity.drop(op.get_bind(), checkfirst=True)
