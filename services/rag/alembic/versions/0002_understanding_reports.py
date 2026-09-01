"""understanding_reports: 项目理解报告（一项目一行，重索引覆盖写）

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "understanding_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,  # 设计 D3：一项目一份最新报告
        ),
        sa.Column("doc_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("mindmap_mermaid", sa.Text(), nullable=False, server_default=""),
        sa.Column("sequences_json", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("understanding_reports")
