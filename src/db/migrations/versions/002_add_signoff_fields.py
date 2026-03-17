"""Add sign-off fields to analysis_outputs

Revision ID: 002
Revises: 001
Create Date: 2024-02-07

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add sign-off columns to analysis_outputs table
    op.add_column('analysis_outputs', 
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'))
    op.add_column('analysis_outputs',
        sa.Column('priority', sa.String(20), nullable=True))
    op.add_column('analysis_outputs',
        sa.Column('reviewed_by', sa.String(255), nullable=True))
    op.add_column('analysis_outputs',
        sa.Column('reviewed_at', sa.DateTime(), nullable=True))
    op.add_column('analysis_outputs',
        sa.Column('engineer_notes', sa.Text(), nullable=True))
    
    # Create index on status for filtering
    op.create_index('idx_analysis_status', 'analysis_outputs', ['status'])
    op.create_index('idx_analysis_priority', 'analysis_outputs', ['priority'])


def downgrade() -> None:
    op.drop_index('idx_analysis_priority', 'analysis_outputs')
    op.drop_index('idx_analysis_status', 'analysis_outputs')
    op.drop_column('analysis_outputs', 'engineer_notes')
    op.drop_column('analysis_outputs', 'reviewed_at')
    op.drop_column('analysis_outputs', 'reviewed_by')
    op.drop_column('analysis_outputs', 'priority')
    op.drop_column('analysis_outputs', 'status')
