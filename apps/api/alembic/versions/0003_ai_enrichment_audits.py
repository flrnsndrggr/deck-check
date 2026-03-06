"""add ai enrichment audits

Revision ID: 0003_ai_enrichment_audits
Revises: 0002_scryfall_cache_tables
Create Date: 2026-03-06 09:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_ai_enrichment_audits"
down_revision = "0002_scryfall_cache_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_enrichment_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_enrichment_audits_family"), "ai_enrichment_audits", ["family"], unique=False)
    op.create_index(op.f("ix_ai_enrichment_audits_payload_hash"), "ai_enrichment_audits", ["payload_hash"], unique=False)
    op.create_index(op.f("ix_ai_enrichment_audits_status"), "ai_enrichment_audits", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_enrichment_audits_status"), table_name="ai_enrichment_audits")
    op.drop_index(op.f("ix_ai_enrichment_audits_payload_hash"), table_name="ai_enrichment_audits")
    op.drop_index(op.f("ix_ai_enrichment_audits_family"), table_name="ai_enrichment_audits")
    op.drop_table("ai_enrichment_audits")
