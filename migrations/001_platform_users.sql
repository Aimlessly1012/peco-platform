-- M12 阶段一：平台用户表（GitHub 登录 + 审核制）
--
-- 表名刻意用 platform_users 而不是 users：RAG 的 M8 已经有一张 users（密码账号），
-- 两者阶段三才合并，现在先并存避免撞车。
CREATE TABLE IF NOT EXISTS platform_users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    github_id     TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    avatar_url    TEXT,
    role          TEXT NOT NULL DEFAULT 'member'  CHECK (role IN ('admin', 'member')),
    -- 首次登录一律 pending，等管理员审批。默认值不要写 approved，否则审核制形同虚设。
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    disabled_at   TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 审核页按待审优先、注册时间倒序取，两个字段都会进条件
CREATE INDEX IF NOT EXISTS idx_platform_users_status ON platform_users (status);
CREATE INDEX IF NOT EXISTS idx_platform_users_created_at ON platform_users (created_at DESC);
