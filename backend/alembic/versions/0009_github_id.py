"""M12：users 加 github_id（平台 GitHub 登录态映射），password_hash 可空

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 可空 + 唯一：密码账号（M8 存量）为 NULL，GitHub 用户填 github_id。
    # Postgres 的唯一约束允许多行 NULL，两类账号可以共存到阶段三清理
    op.add_column("users", sa.Column("github_id", sa.String(64), nullable=True))
    op.create_index("ix_users_github_id", "users", ["github_id"], unique=True)
    # GitHub 用户没有密码，原 NOT NULL 会挡住建档
    op.alter_column(
        "users", "password_hash",
        existing_type=sa.String(128), nullable=False, server_default="",
    )


def downgrade() -> None:
    op.alter_column(
        "users", "password_hash",
        existing_type=sa.String(128), nullable=False, server_default=None,
    )
    op.drop_index("ix_users_github_id", "users")
    op.drop_column("users", "github_id")
