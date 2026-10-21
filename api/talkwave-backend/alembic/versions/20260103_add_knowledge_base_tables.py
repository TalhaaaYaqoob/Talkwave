"""add knowledge base tables

Revision ID: 20260103_kb
Revises: fefdd1835b7d
Create Date: 2026-01-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = '20260103_kb'
down_revision = 'fefdd1835b7d'
branch_labels = None
depends_on = None


def upgrade():
    # Create knowledge_base_documents table
    op.create_table(
        'knowledge_base_documents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('file_type', sa.String(length=50), nullable=False),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('chunk_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('processing_status', sa.String(length=50), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('processing_error', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_kb_documents_organization_id', 'knowledge_base_documents', ['organization_id'], unique=False)
    op.create_index('ix_kb_documents_name', 'knowledge_base_documents', ['name'], unique=False)
    op.create_index('ix_kb_documents_status', 'knowledge_base_documents', ['processing_status'], unique=False)

    # Create knowledge_base_chunks table
    op.create_table(
        'knowledge_base_chunks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('embedding', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['knowledge_base_documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_kb_chunks_document_id', 'knowledge_base_chunks', ['document_id'], unique=False)
    op.create_index('ix_kb_chunks_document_index', 'knowledge_base_chunks', ['document_id', 'chunk_index'], unique=True)


def downgrade():
    op.drop_table('knowledge_base_chunks')
    op.drop_table('knowledge_base_documents')

