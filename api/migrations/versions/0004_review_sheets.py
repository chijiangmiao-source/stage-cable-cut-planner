"""add review_sheets and review_measurements

Material review sheets (用料复核单): one sheet per plan recording the uniform
tolerance and the computed batch verdict, plus one measurement row per roll
storing the theoretical baseline, the measured leftover and the computed
deviation/verdict. Both tables are new, so historical plans stay untouched
and remain directly accessible; a plan simply has no sheet until the foreman
creates one.

Revision ID: 0004_review_sheets
Revises: 0003_cut_kit_id
Create Date: 2026-09-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_review_sheets"
down_revision: Union[str, None] = "0003_cut_kit_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_sheets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("tolerance_mm", sa.Integer(), nullable=False),
        sa.Column("batch_ok", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("plan_id"),
    )
    op.create_index("ix_review_sheets_plan_id", "review_sheets", ["plan_id"])
    op.create_table(
        "review_measurements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sheet_id", sa.Integer(), nullable=False),
        sa.Column("roll_position", sa.Integer(), nullable=False),
        sa.Column("theoretical_leftover", sa.Integer(), nullable=False),
        sa.Column("measured_leftover", sa.Integer(), nullable=False),
        sa.Column("deviation", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["sheet_id"], ["review_sheets.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_review_measurements_sheet_id", "review_measurements", ["sheet_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_review_measurements_sheet_id", table_name="review_measurements")
    op.drop_table("review_measurements")
    op.drop_index("ix_review_sheets_plan_id", table_name="review_sheets")
    op.drop_table("review_sheets")
