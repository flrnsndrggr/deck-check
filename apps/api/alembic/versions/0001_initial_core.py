"""initial core schema

Revision ID: 0001_initial_core
Revises: 
Create Date: 2026-03-05 09:30:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_source_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("warning", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_data_source_status_source_key"), "data_source_status", ["source_key"], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default="Untitled Project"),
        sa.Column("decklist_text", sa.Text(), nullable=False),
        sa.Column("bracket", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "rules_references",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "run_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("policy", sa.String(length=64), nullable=False),
        sa.Column("turn_limit", sa.Integer(), nullable=False),
        sa.Column("bracket", sa.Integer(), nullable=False),
        sa.Column("template_preset", sa.String(length=64), nullable=False, server_default="balanced"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "sim_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sim_jobs_job_id"), "sim_jobs", ["job_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_sim_jobs_job_id"), table_name="sim_jobs")
    op.drop_table("sim_jobs")
    op.drop_table("run_records")
    op.drop_table("rules_references")
    op.drop_table("projects")
    op.drop_index(op.f("ix_data_source_status_source_key"), table_name="data_source_status")
    op.drop_table("data_source_status")
