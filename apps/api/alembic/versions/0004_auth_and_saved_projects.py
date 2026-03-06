"""auth and saved projects

Revision ID: 0004_auth_and_saved_projects
Revises: 0003_ai_enrichment_audits
Create Date: 2026-03-06 17:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_auth_and_saved_projects"
down_revision = "0003_ai_enrichment_audits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("csrf_token", sa.String(length=128), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], unique=False)

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"], unique=False)
    op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)
    op.create_index("ix_password_reset_tokens_email", "password_reset_tokens", ["email"], unique=False)
    op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"], unique=False)

    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("name_key", sa.String(length=200), server_default="untitled-project", nullable=False))
        batch_op.add_column(sa.Column("deck_name", sa.String(length=200), server_default="Untitled Deck", nullable=False))
        batch_op.add_column(sa.Column("commander_label", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("summary", sa.JSON(), server_default=sa.text("'{}'"), nullable=False))
        batch_op.add_column(sa.Column("saved_bundle", sa.JSON(), server_default=sa.text("'{}'"), nullable=False))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
        batch_op.create_index("ix_projects_user_id", ["user_id"], unique=False)
        batch_op.create_index("ix_projects_name_key", ["name_key"], unique=False)
        batch_op.create_foreign_key("fk_projects_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE")

    op.create_unique_constraint("uq_projects_user_id_name_key", "projects", ["user_id", "name_key"])

    op.create_table(
        "project_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("deck_name", sa.String(length=200), nullable=False),
        sa.Column("commander_label", sa.String(length=255), nullable=True),
        sa.Column("decklist_text", sa.Text(), nullable=False),
        sa.Column("bracket", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("summary", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("saved_bundle", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_project_versions_project_id", "project_versions", ["project_id"], unique=False)
    op.create_unique_constraint("uq_project_versions_project_id_version_number", "project_versions", ["project_id", "version_number"])


def downgrade() -> None:
    op.drop_constraint("uq_project_versions_project_id_version_number", "project_versions", type_="unique")
    op.drop_index("ix_project_versions_project_id", table_name="project_versions")
    op.drop_table("project_versions")

    op.drop_constraint("uq_projects_user_id_name_key", "projects", type_="unique")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("fk_projects_user_id_users", type_="foreignkey")
        batch_op.drop_index("ix_projects_name_key")
        batch_op.drop_index("ix_projects_user_id")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("saved_bundle")
        batch_op.drop_column("summary")
        batch_op.drop_column("commander_label")
        batch_op.drop_column("deck_name")
        batch_op.drop_column("name_key")
        batch_op.drop_column("user_id")

    op.drop_index("ix_password_reset_tokens_expires_at", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_email", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
