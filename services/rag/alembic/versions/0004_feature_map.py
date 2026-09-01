"""M6：understanding_reports 加 feature_map_markdown（需求功能思维导图）

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 旧报告没有功能导图 → nullable，前端回退渲染 mindmap_mermaid 并提示重新索引
    op.add_column(
        "understanding_reports",
        sa.Column("feature_map_markdown", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("understanding_reports", "feature_map_markdown")
