# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add teamspace public visibility review state.

Revision ID: 025_team_visibility_review
Revises: 024_shareable_teamspaces
"""

import sqlalchemy as sa

from alembic import op

revision = "025_team_visibility_review"
down_revision = "024_shareable_teamspaces"
branch_labels = None
depends_on = None


def _has_column(name: str) -> bool:
    return name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("teams")}


def _has_check(name: str) -> bool:
    return any(check["name"] == name for check in sa.inspect(op.get_bind()).get_check_constraints("teams"))


def _has_foreign_key(name: str) -> bool:
    return any(key["name"] == name for key in sa.inspect(op.get_bind()).get_foreign_keys("teams"))


def upgrade() -> None:
    columns = (
        sa.Column("visibility_request_status", sa.String(length=16), nullable=True),
        sa.Column("visibility_requested_by", sa.UUID(), nullable=True),
        sa.Column("visibility_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("visibility_reviewed_by", sa.UUID(), nullable=True),
        sa.Column("visibility_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("visibility_rejection_reason", sa.String(length=500), nullable=True),
    )
    for column in columns:
        if not _has_column(column.name):
            op.add_column("teams", column)

    if not _has_check("ck_teams_visibility_request_status"):
        op.create_check_constraint(
            "ck_teams_visibility_request_status",
            "teams",
            "visibility_request_status IS NULL OR visibility_request_status IN ('pending', 'approved', 'rejected')",
        )
    if not _has_check("ck_teams_pending_visibility_private"):
        op.create_check_constraint(
            "ck_teams_pending_visibility_private",
            "teams",
            "visibility_request_status != 'pending' OR is_private",
        )
    if not _has_check("ck_teams_pending_visibility_requested_at"):
        op.create_check_constraint(
            "ck_teams_pending_visibility_requested_at",
            "teams",
            "visibility_request_status != 'pending' OR visibility_requested_at IS NOT NULL",
        )
    if not _has_foreign_key("fk_teams_visibility_requested_by_users"):
        op.create_foreign_key(
            "fk_teams_visibility_requested_by_users",
            "teams",
            "users",
            ["visibility_requested_by"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_foreign_key("fk_teams_visibility_reviewed_by_users"):
        op.create_foreign_key(
            "fk_teams_visibility_reviewed_by_users",
            "teams",
            "users",
            ["visibility_reviewed_by"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    if _has_foreign_key("fk_teams_visibility_reviewed_by_users"):
        op.drop_constraint("fk_teams_visibility_reviewed_by_users", "teams", type_="foreignkey")
    if _has_foreign_key("fk_teams_visibility_requested_by_users"):
        op.drop_constraint("fk_teams_visibility_requested_by_users", "teams", type_="foreignkey")
    if _has_check("ck_teams_pending_visibility_requested_at"):
        op.drop_constraint("ck_teams_pending_visibility_requested_at", "teams", type_="check")
    if _has_check("ck_teams_pending_visibility_private"):
        op.drop_constraint("ck_teams_pending_visibility_private", "teams", type_="check")
    if _has_check("ck_teams_visibility_request_status"):
        op.drop_constraint("ck_teams_visibility_request_status", "teams", type_="check")
    for name in (
        "visibility_rejection_reason",
        "visibility_reviewed_at",
        "visibility_reviewed_by",
        "visibility_requested_at",
        "visibility_requested_by",
        "visibility_request_status",
    ):
        if _has_column(name):
            op.drop_column("teams", name)
