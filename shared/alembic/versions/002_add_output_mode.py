"""add output_mode to tasks

Revision ID: 002
Revises: 001
Create Date: 2026-04-16 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("output_mode", sa.String(10), nullable=True, server_default="audio"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "output_mode")
