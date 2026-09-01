"""M12 阶段三：删除 M8 的密码账号体系（invite_codes 表与 users.password_hash）。

身份改由平台的 GitHub 登录提供（platform_users + JWS cookie），密码登录与邀请码
注册的接口、模型、测试都已移除，这里清理数据层残留。

不可逆：降级只重建结构，历史邀请码与密码哈希不还原（服务器上已备份在
~/backups/m8-auth-data-*.sql）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("invite_codes")
    op.drop_column("users", "password_hash")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False, unique=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("used_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
