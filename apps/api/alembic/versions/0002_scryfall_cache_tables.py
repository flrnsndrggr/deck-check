"""add scryfall cache tables

Revision ID: 0002_scryfall_cache_tables
Revises: 0001_initial_core
Create Date: 2026-03-05 09:45:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_scryfall_cache_tables"
down_revision = "0001_initial_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scryfall_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("oracle_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scryfall_cards_oracle_id"), "scryfall_cards", ["oracle_id"], unique=True)
    op.create_index(op.f("ix_scryfall_cards_name"), "scryfall_cards", ["name"], unique=False)

    op.create_table(
        "scryfall_names",
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("oracle_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["oracle_id"], ["scryfall_cards.oracle_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_index(op.f("ix_scryfall_names_oracle_id"), "scryfall_names", ["oracle_id"], unique=False)

    op.create_table(
        "scryfall_rulings",
        sa.Column("oracle_id", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("oracle_id"),
    )


def downgrade() -> None:
    op.drop_table("scryfall_rulings")
    op.drop_index(op.f("ix_scryfall_names_oracle_id"), table_name="scryfall_names")
    op.drop_table("scryfall_names")
    op.drop_index(op.f("ix_scryfall_cards_name"), table_name="scryfall_cards")
    op.drop_index(op.f("ix_scryfall_cards_oracle_id"), table_name="scryfall_cards")
    op.drop_table("scryfall_cards")
