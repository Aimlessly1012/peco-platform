"""M5：understanding_reports 加 dataflow_mermaid、projects 加 index_depth

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 旧报告没有数据流图 → nullable，前端据此隐藏该卡片
    op.add_column(
        "understanding_reports",
        sa.Column("dataflow_mermaid", sa.Text(), nullable=True),
    )
    # 存量项目按 deep 处理：它们的报告确实是深度产物
    op.add_column(
        "projects",
        sa.Column(
            "index_depth", sa.String(10), nullable=False, server_default="deep"
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "index_depth")
    op.drop_column("understanding_reports", "dataflow_mermaid")
