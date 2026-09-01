"""M6 B7：understanding_reports 加 page_map_markdown（页面结构导图）

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 旧报告没有页面导图 → nullable，前端隐藏该卡片
    op.add_column(
        "understanding_reports",
        sa.Column("page_map_markdown", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("understanding_reports", "page_map_markdown")
