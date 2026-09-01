"""M11：users 加 disabled_at / last_login_at

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 均可空：NULL = 未禁用 / 从未登录。存量用户自然落在"启用且无登录记录"
    op.add_column(
        "users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "disabled_at")
