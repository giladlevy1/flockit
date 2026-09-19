"""AI developer workbenches, Slack links, onboarding

Revision ID: 71362f356b01
Revises: 0003
Create Date: 2026-09-20 02:16:13.298371
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('environment',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('services', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('secret_names', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('setup_script', sa.Text(), nullable=True),
    sa.Column('persistent', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'name', name='uq_environment_org_name')
    )
    op.create_index(op.f('ix_environment_org_id'), 'environment', ['org_id'], unique=False)
    op.add_column('user', sa.Column('environment_id', sa.UUID(), nullable=True))
    op.add_column('user', sa.Column('default_repo', sa.String(length=300), nullable=True))
    op.add_column('user', sa.Column('slack_user_id', sa.String(length=32), nullable=True))
    op.add_column('user', sa.Column('slack_link_code_hash', sa.String(length=64), nullable=True))
    op.add_column('user', sa.Column('slack_link_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_user_slack_link_code_hash'), 'user', ['slack_link_code_hash'], unique=False)
    op.add_column('user', sa.Column('onboarded_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_user_slack_user_id'), 'user', ['slack_user_id'], unique=False)
    op.create_foreign_key('user_environment_id_fkey', 'user', 'environment', ['environment_id'], ['id'], ondelete='SET NULL')
    op.add_column('api_token', sa.Column('kind', sa.String(length=16), server_default='collector', nullable=False))
    op.add_column('workflow_run', sa.Column('notify', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('workflow_run', 'notify')
    op.drop_column('api_token', 'kind')
    op.drop_constraint('user_environment_id_fkey', 'user', type_='foreignkey')
    op.drop_index(op.f('ix_user_slack_user_id'), table_name='user')
    op.drop_index(op.f('ix_user_slack_link_code_hash'), table_name='user')
    op.drop_column('user', 'slack_link_expires_at')
    op.drop_column('user', 'slack_link_code_hash')
    op.drop_column('user', 'default_repo')
    op.drop_column('user', 'onboarded_at')
    op.drop_column('user', 'slack_user_id')
    op.drop_column('user', 'environment_id')
    op.drop_index(op.f('ix_environment_org_id'), table_name='environment')
    op.drop_table('environment')
