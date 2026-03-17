"""Initial analysis_outputs table

Revision ID: 001
Revises: 
Create Date: 2026-02-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analysis_outputs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('fund_id', sa.String(50), nullable=True, index=True),
        sa.Column('analysis_type', sa.String(100), nullable=False, index=True),
        sa.Column('insights', sa.Text(), nullable=False),
        sa.Column('recommendations', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, index=True),
        sa.Column('agent_mode', sa.String(20), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('analysis_outputs')

