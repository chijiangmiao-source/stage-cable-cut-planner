"""add cuts.kit_id

Records the optional kit (套组) marker of each cut. Segments sharing a kit
id are kept on a single roll by the solver. The column is nullable with no
default, so every historical cut keeps NULL (= an independent segment) and
all historical plans continue to return their original results.

Revision ID: 0003_cut_kit_id
Revises: 0002_cut_completed_at
Create Date: 2026-09-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_cut_kit_id"
down_revision: Union[str, None] = "0002_cut_completed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cuts",
        sa.Column("kit_id", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cuts", "kit_id")
