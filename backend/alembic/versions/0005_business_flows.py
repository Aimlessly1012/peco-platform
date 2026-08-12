"""M6 B5：understanding_reports 加 business_flows_json（业务流程图）

顺延而非合并进 0004——0004 若已在任何环境执行过，合并后的新列不会被补上。
独立一条迁移无论 0004 跑没跑过都能正确落地。

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # [{title, mermaid, fallback_text}]；旧报告与 fast 产物为 NULL，前端隐藏该卡片
    op.add_column(
        "understanding_reports",
        sa.Column("business_flows_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("understanding_reports", "business_flows_json")
