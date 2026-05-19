"""subtask lifecycle columns + sub-record tables (comments, attachments, proofs)

Revision ID: b7e9c2d1a4f5
Revises: 0bb67d2bc035
Create Date: 2026-05-19 16:10:00.000000

Adds mission-like lifecycle columns to mission_subtask (creator_id,
description, status, start_date, deadline, finish_date, created_at,
updated_at) and creates three new sub-record tables that mirror the
mission-level ones: mission_subtask_comment, mission_subtask_attachment,
mission_subtask_proof.

There is intentionally no reviewer_id on the subtask side — approval
stays at the parent mission level.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e9c2d1a4f5'
down_revision: Union[str, Sequence[str], None] = '0bb67d2bc035'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extend mission_subtask ────────────────────────────────────────────
    op.add_column('mission_subtask', sa.Column('creator_id', sa.BigInteger(), nullable=True))
    op.add_column('mission_subtask', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('mission_subtask', sa.Column('status', sa.String(30), nullable=True, server_default='not_started'))
    op.add_column('mission_subtask', sa.Column('start_date', sa.Date(), server_default=sa.text('CURRENT_DATE'), nullable=True))
    op.add_column('mission_subtask', sa.Column('deadline', sa.Date(), nullable=True))
    op.add_column('mission_subtask', sa.Column('finish_date', sa.Date(), nullable=True))
    op.add_column('mission_subtask', sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True))
    op.add_column('mission_subtask', sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True))
    op.create_foreign_key('fk_mission_subtask_creator_id', 'mission_subtask', 'user', ['creator_id'], ['id'])

    # ── mission_subtask_comment ──────────────────────────────────────────
    op.create_table(
        'mission_subtask_comment',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('subtask_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('attachment', sa.String(500), nullable=True),
        sa.Column('creator_name', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.ForeignKeyConstraint(['subtask_id'], ['mission_subtask.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_mission_subtask_comment_id'), 'mission_subtask_comment', ['id'], unique=False)

    # ── mission_subtask_attachment ───────────────────────────────────────
    op.create_table(
        'mission_subtask_attachment',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('subtask_id', sa.BigInteger(), nullable=False),
        sa.Column('file', sa.String(500), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('note', sa.String(255), nullable=True),
        sa.Column('creator_name', sa.String(255), nullable=True),
        sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.ForeignKeyConstraint(['subtask_id'], ['mission_subtask.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_mission_subtask_attachment_id'), 'mission_subtask_attachment', ['id'], unique=False)

    # ── mission_subtask_proof ────────────────────────────────────────────
    op.create_table(
        'mission_subtask_proof',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('subtask_id', sa.BigInteger(), nullable=False),
        sa.Column('file', sa.String(500), nullable=False),
        sa.Column('comment', sa.String(255), nullable=True),
        sa.Column('creator_name', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.ForeignKeyConstraint(['subtask_id'], ['mission_subtask.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_mission_subtask_proof_id'), 'mission_subtask_proof', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_mission_subtask_proof_id'), table_name='mission_subtask_proof')
    op.drop_table('mission_subtask_proof')
    op.drop_index(op.f('ix_mission_subtask_attachment_id'), table_name='mission_subtask_attachment')
    op.drop_table('mission_subtask_attachment')
    op.drop_index(op.f('ix_mission_subtask_comment_id'), table_name='mission_subtask_comment')
    op.drop_table('mission_subtask_comment')

    op.drop_constraint('fk_mission_subtask_creator_id', 'mission_subtask', type_='foreignkey')
    op.drop_column('mission_subtask', 'updated_at')
    op.drop_column('mission_subtask', 'created_at')
    op.drop_column('mission_subtask', 'finish_date')
    op.drop_column('mission_subtask', 'deadline')
    op.drop_column('mission_subtask', 'start_date')
    op.drop_column('mission_subtask', 'status')
    op.drop_column('mission_subtask', 'description')
    op.drop_column('mission_subtask', 'creator_id')
