"""LLM-generated explanation on question versions

Revision ID: 0003_ai_explanation
Revises: 0002_roles_and_test_visibility
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ai_explanation"
down_revision: Union[str, None] = "0002_roles_and_test_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("question_versions", sa.Column("ai_explanation", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("question_versions", "ai_explanation")
