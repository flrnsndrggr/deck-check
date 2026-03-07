"""admin console foundation

Revision ID: 0005_admin_console_foundation
Revises: 0004_auth_and_saved_projects
Create Date: 2026-03-07 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_admin_console_foundation"
down_revision = "0004_auth_and_saved_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(length=32), server_default="user", nullable=False))
        batch_op.add_column(sa.Column("status", sa.String(length=32), server_default="active", nullable=False))
        batch_op.add_column(sa.Column("plan", sa.String(length=32), server_default="free", nullable=False))
        batch_op.add_column(sa.Column("admin_notes", sa.Text(), nullable=True))

    op.create_table(
        "problem_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="error"),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("path", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_email", sa.String(length=320), nullable=True),
        sa.Column("context", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_problem_events_level", "problem_events", ["level"], unique=False)
    op.create_index("ix_problem_events_source", "problem_events", ["source"], unique=False)
    op.create_index("ix_problem_events_category", "problem_events", ["category"], unique=False)
    op.create_index("ix_problem_events_path", "problem_events", ["path"], unique=False)
    op.create_index("ix_problem_events_request_id", "problem_events", ["request_id"], unique=False)
    op.create_index("ix_problem_events_user_id", "problem_events", ["user_id"], unique=False)
    op.create_index("ix_problem_events_user_email", "problem_events", ["user_email"], unique=False)
    op.create_index("ix_problem_events_created_at", "problem_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_problem_events_created_at", table_name="problem_events")
    op.drop_index("ix_problem_events_user_email", table_name="problem_events")
    op.drop_index("ix_problem_events_user_id", table_name="problem_events")
    op.drop_index("ix_problem_events_request_id", table_name="problem_events")
    op.drop_index("ix_problem_events_path", table_name="problem_events")
    op.drop_index("ix_problem_events_category", table_name="problem_events")
    op.drop_index("ix_problem_events_source", table_name="problem_events")
    op.drop_index("ix_problem_events_level", table_name="problem_events")
    op.drop_table("problem_events")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("admin_notes")
        batch_op.drop_column("plan")
        batch_op.drop_column("status")
        batch_op.drop_column("role")
