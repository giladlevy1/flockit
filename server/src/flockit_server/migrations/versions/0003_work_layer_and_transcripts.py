"""work layer and transcripts

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-19 23:36:55.559069
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ENUMS = {
    "user_kind": ("human", "ai"),
    "dispatch_mode": ("off", "ask", "auto"),
    "run_mode": ("ask", "auto"),
    "permission_profile": ("read_only", "edit", "full"),
    "run_status": ("offered", "queued", "starting", "running", "succeeded", "failed", "declined", "cancelled"),
}


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)
    op.create_table('audit_event',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['user.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_event_org_id'), 'audit_event', ['org_id'], unique=False)
    op.create_index('ix_audit_org_created', 'audit_event', ['org_id', 'created_at'], unique=False)
    op.create_table('machine',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('pool', sa.String(length=64), nullable=True),
    sa.Column('token_hash', sa.String(length=64), nullable=True),
    sa.Column('token_prefix', sa.String(length=16), nullable=True),
    sa.Column('platform', sa.String(length=64), nullable=True),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('capacity', sa.Integer(), server_default='1', nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_machine_org_id'), 'machine', ['org_id'], unique=False)
    op.create_index(op.f('ix_machine_user_id'), 'machine', ['user_id'], unique=False)
    op.create_table('workflow',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('prompt_template', sa.Text(), nullable=False),
    sa.Column('repo', sa.String(length=300), nullable=False),
    sa.Column('base_branch', sa.String(length=200), nullable=True),
    sa.Column('assignee_id', sa.UUID(), nullable=False),
    sa.Column('mode', postgresql.ENUM('ask', 'auto', name='run_mode', create_type=False), nullable=False),
    sa.Column('permission_profile', postgresql.ENUM('read_only', 'edit', 'full', name='permission_profile', create_type=False), nullable=False),
    sa.Column('schedule_cron', sa.String(length=120), nullable=True),
    sa.Column('schedule_timezone', sa.String(length=64), server_default='UTC', nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('webhook_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('webhook_secret_hash', sa.String(length=64), nullable=True),
    sa.Column('webhook_filter', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assignee_id'], ['user.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('webhook_secret_hash')
    )
    op.create_index(op.f('ix_workflow_next_run_at'), 'workflow', ['next_run_at'], unique=False)
    op.create_index(op.f('ix_workflow_org_id'), 'workflow', ['org_id'], unique=False)
    op.create_table('session_file',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('path', sa.String(length=500), nullable=False),
    sa.Column('edits', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['session.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('session_id', 'path')
    )
    op.create_table('session_message',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('entry_id', sa.String(length=64), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('tool_name', sa.String(length=80), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('search', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['session.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'entry_id', name='uq_session_message_entry')
    )
    op.create_index('ix_session_message_search', 'session_message', ['search'], unique=False, postgresql_using='gin')
    op.create_index('ix_session_message_session_seq', 'session_message', ['session_id', 'seq'], unique=False)
    op.add_column('api_token', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('api_token', sa.Column('run_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_api_token_run', 'api_token', 'workflow_run', ['run_id'], ['id'], ondelete='CASCADE')
    op.add_column('session', sa.Column('actor_id', sa.UUID(), nullable=True))
    op.add_column('session', sa.Column('title', sa.String(length=300), nullable=True))
    op.add_column('session', sa.Column('tokens_input', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('session', sa.Column('tokens_output', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('session', sa.Column('tokens_cache_read', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('session', sa.Column('tokens_cache_write', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('session', sa.Column('tool_calls', sa.Integer(), server_default='0', nullable=False))
    op.add_column('session', sa.Column('message_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('session', sa.Column('files_touched', sa.Integer(), server_default='0', nullable=False))
    op.create_index(op.f('ix_session_actor_id'), 'session', ['actor_id'], unique=False)
    op.create_foreign_key('fk_session_actor', 'session', 'user', ['actor_id'], ['id'], ondelete='RESTRICT')
    op.add_column('user', sa.Column('kind', postgresql.ENUM('human', 'ai', name='user_kind', create_type=False), server_default='human', nullable=False))
    op.add_column('user', sa.Column('dispatch_mode', postgresql.ENUM('off', 'ask', 'auto', name='dispatch_mode', create_type=False), server_default='ask', nullable=False))
    op.add_column('user', sa.Column('agent_vendor', sa.String(length=64), nullable=True))
    op.add_column('user', sa.Column('agent_model', sa.String(length=120), nullable=True))
    op.add_column('user', sa.Column('runner_pool', sa.String(length=64), nullable=True))
    op.add_column('user', sa.Column('sponsor_id', sa.UUID(), nullable=True))
    op.add_column('user', sa.Column('instructions', sa.Text(), nullable=True))
    op.create_foreign_key('fk_user_sponsor', 'user', 'user', ['sponsor_id'], ['id'], ondelete='SET NULL')
    op.add_column('workflow_run', sa.Column('workflow_id', sa.UUID(), nullable=True))
    op.add_column('workflow_run', sa.Column('title', sa.String(length=300), server_default='Task', nullable=False))
    op.add_column('workflow_run', sa.Column('prompt', sa.Text(), server_default='', nullable=False))
    op.add_column('workflow_run', sa.Column('repo', sa.String(length=300), nullable=True))
    op.add_column('workflow_run', sa.Column('base_branch', sa.String(length=200), nullable=True))
    op.add_column('workflow_run', sa.Column('branch', sa.String(length=200), nullable=True))
    op.add_column('workflow_run', sa.Column('assignee_id', sa.UUID(), nullable=True))
    op.add_column('workflow_run', sa.Column('mode', postgresql.ENUM('ask', 'auto', name='run_mode', create_type=False), server_default='ask', nullable=False))
    op.add_column('workflow_run', sa.Column('permission_profile', postgresql.ENUM('read_only', 'edit', 'full', name='permission_profile', create_type=False), server_default='edit', nullable=False))
    op.add_column('workflow_run', sa.Column('trigger', sa.String(length=32), server_default='manual', nullable=False))
    op.add_column('workflow_run', sa.Column('trigger_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('workflow_run', sa.Column('machine_id', sa.UUID(), nullable=True))
    op.add_column('workflow_run', sa.Column('session_id', sa.UUID(), nullable=True))
    op.add_column('workflow_run', sa.Column('interactive', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('workflow_run', sa.Column('result', sa.Text(), nullable=True))
    op.add_column('workflow_run', sa.Column('error', sa.Text(), nullable=True))
    op.add_column('workflow_run', sa.Column('pr_url', sa.String(length=500), nullable=True))
    op.add_column('workflow_run', sa.Column('cost_usd', sa.Float(), nullable=True))
    op.add_column('workflow_run', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('workflow_run', sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('workflow_run', sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TABLE workflow_run ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE workflow_run ALTER COLUMN status TYPE run_status USING "
        "(CASE WHEN status IN ('offered','queued','starting','running','succeeded','failed','declined','cancelled') "
        "THEN status ELSE 'queued' END)::run_status"
    )
    op.execute("ALTER TABLE workflow_run ALTER COLUMN status SET DEFAULT 'queued'")
    op.create_index('ix_run_assignee_status', 'workflow_run', ['assignee_id', 'status'], unique=False)
    op.create_index('ix_run_org_created', 'workflow_run', ['org_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_workflow_run_workflow_id'), 'workflow_run', ['workflow_id'], unique=False)
    op.create_foreign_key('fk_run_session', 'workflow_run', 'session', ['session_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_run_assignee', 'workflow_run', 'user', ['assignee_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_run_workflow', 'workflow_run', 'workflow', ['workflow_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_run_machine', 'workflow_run', 'machine', ['machine_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_run_machine', 'workflow_run', type_='foreignkey')
    op.drop_constraint('fk_run_workflow', 'workflow_run', type_='foreignkey')
    op.drop_constraint('fk_run_assignee', 'workflow_run', type_='foreignkey')
    op.drop_constraint('fk_run_session', 'workflow_run', type_='foreignkey')
    op.drop_index(op.f('ix_workflow_run_workflow_id'), table_name='workflow_run')
    op.drop_index('ix_run_org_created', table_name='workflow_run')
    op.drop_index('ix_run_assignee_status', table_name='workflow_run')
    op.execute("ALTER TABLE workflow_run ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE workflow_run ALTER COLUMN status TYPE varchar(32) USING status::text")
    op.drop_column('workflow_run', 'notified_at')
    op.drop_column('workflow_run', 'accepted_at')
    op.drop_column('workflow_run', 'updated_at')
    op.drop_column('workflow_run', 'cost_usd')
    op.drop_column('workflow_run', 'pr_url')
    op.drop_column('workflow_run', 'error')
    op.drop_column('workflow_run', 'result')
    op.drop_column('workflow_run', 'interactive')
    op.drop_column('workflow_run', 'session_id')
    op.drop_column('workflow_run', 'machine_id')
    op.drop_column('workflow_run', 'trigger_payload')
    op.drop_column('workflow_run', 'trigger')
    op.drop_column('workflow_run', 'permission_profile')
    op.drop_column('workflow_run', 'mode')
    op.drop_column('workflow_run', 'assignee_id')
    op.drop_column('workflow_run', 'branch')
    op.drop_column('workflow_run', 'base_branch')
    op.drop_column('workflow_run', 'repo')
    op.drop_column('workflow_run', 'prompt')
    op.drop_column('workflow_run', 'title')
    op.drop_column('workflow_run', 'workflow_id')
    op.drop_constraint('fk_user_sponsor', 'user', type_='foreignkey')
    op.drop_column('user', 'instructions')
    op.drop_column('user', 'sponsor_id')
    op.drop_column('user', 'runner_pool')
    op.drop_column('user', 'agent_model')
    op.drop_column('user', 'agent_vendor')
    op.drop_column('user', 'dispatch_mode')
    op.drop_column('user', 'kind')
    op.drop_constraint('fk_session_actor', 'session', type_='foreignkey')
    op.drop_index(op.f('ix_session_actor_id'), table_name='session')
    op.drop_column('session', 'files_touched')
    op.drop_column('session', 'message_count')
    op.drop_column('session', 'tool_calls')
    op.drop_column('session', 'tokens_cache_write')
    op.drop_column('session', 'tokens_cache_read')
    op.drop_column('session', 'tokens_output')
    op.drop_column('session', 'tokens_input')
    op.drop_column('session', 'title')
    op.drop_column('session', 'actor_id')
    op.drop_constraint('fk_api_token_run', 'api_token', type_='foreignkey')
    op.drop_column('api_token', 'run_id')
    op.drop_column('api_token', 'expires_at')
    op.drop_index('ix_session_message_session_seq', table_name='session_message')
    op.drop_index('ix_session_message_search', table_name='session_message', postgresql_using='gin')
    op.drop_table('session_message')
    op.drop_table('session_file')
    op.drop_index(op.f('ix_workflow_org_id'), table_name='workflow')
    op.drop_index(op.f('ix_workflow_next_run_at'), table_name='workflow')
    op.drop_table('workflow')
    op.drop_index(op.f('ix_machine_user_id'), table_name='machine')
    op.drop_index(op.f('ix_machine_org_id'), table_name='machine')
    op.drop_table('machine')
    op.drop_index('ix_audit_org_created', table_name='audit_event')
    op.drop_index(op.f('ix_audit_event_org_id'), table_name='audit_event')
    op.drop_table('audit_event')
    for name in ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {name}")
