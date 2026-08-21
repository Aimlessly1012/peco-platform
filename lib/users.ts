import { query } from "./db";

export type UserRole = "admin" | "member";
export type UserStatus = "pending" | "approved" | "rejected";

export interface PlatformUser {
  id: string;
  github_id: string;
  name: string;
  avatar_url: string | null;
  role: UserRole;
  status: UserStatus;
  disabled_at: string | null;
  last_login_at: string | null;
  created_at: string;
}

/** 能不能进受保护区域：批准过、且没被禁用。 */
export function isActive(u: Pick<PlatformUser, "status" | "disabled_at"> | null): boolean {
  return !!u && u.status === "approved" && !u.disabled_at;
}

/** 环境变量指定的管理员 GitHub 数字 id。 */
function adminGithubId(): string | null {
  const id = (process.env.ADMIN_GITHUB_ID || "").trim();
  return id || null;
}

/**
 * GitHub 登录后 upsert。
 *
 * 新用户一律落 pending —— 只有 ADMIN_GITHUB_ID 指定的那个账号例外，
 * 否则第一个管理员自己也进不来。已存在的用户只更新画像与登录时间，
 * **不碰 status / role**：审核结果不能被一次登录冲掉。
 */
export async function upsertOnLogin(input: {
  githubId: string;
  name: string;
  avatarUrl: string | null;
}): Promise<PlatformUser> {
  const isAdmin = adminGithubId() !== null && input.githubId === adminGithubId();
  const rows = await query<PlatformUser>(
    `INSERT INTO platform_users (github_id, name, avatar_url, role, status, last_login_at)
     VALUES ($1, $2, $3, $4, $5, now())
     ON CONFLICT (github_id) DO UPDATE
       SET name = EXCLUDED.name,
           avatar_url = EXCLUDED.avatar_url,
           last_login_at = now()
     RETURNING *`,
    [
      input.githubId,
      input.name,
      input.avatarUrl,
      isAdmin ? "admin" : "member",
      isAdmin ? "approved" : "pending",
    ]
  );
  return rows[0];
}

export async function getByGithubId(githubId: string): Promise<PlatformUser | null> {
  const rows = await query<PlatformUser>(
    "SELECT * FROM platform_users WHERE github_id = $1",
    [githubId]
  );
  return rows[0] ?? null;
}

/** 审核页列表：待审的排最前，其余按注册时间倒序。 */
export async function listUsers(): Promise<PlatformUser[]> {
  return query<PlatformUser>(
    `SELECT * FROM platform_users
     ORDER BY (status = 'pending') DESC, created_at DESC`
  );
}

export type UserAction = "approve" | "reject" | "disable" | "enable";

/**
 * 审核操作。两条自锁护栏（不能操作自己、不能动最后一个可用 admin）在调用侧校验，
 * 这里只管落库。
 */
export async function applyAction(id: string, action: UserAction): Promise<PlatformUser | null> {
  const sql: Record<UserAction, string> = {
    approve: "UPDATE platform_users SET status = 'approved', disabled_at = NULL WHERE id = $1 RETURNING *",
    reject: "UPDATE platform_users SET status = 'rejected' WHERE id = $1 RETURNING *",
    disable: "UPDATE platform_users SET disabled_at = now() WHERE id = $1 RETURNING *",
    enable: "UPDATE platform_users SET disabled_at = NULL WHERE id = $1 RETURNING *",
  };
  const rows = await query<PlatformUser>(sql[action], [id]);
  return rows[0] ?? null;
}

export async function getById(id: string): Promise<PlatformUser | null> {
  const rows = await query<PlatformUser>("SELECT * FROM platform_users WHERE id = $1", [id]);
  return rows[0] ?? null;
}

/** 还剩几个能登录的管理员——用于挡住「把最后一个管理员踢出去」。 */
export async function countActiveAdmins(excludeId?: string): Promise<number> {
  const rows = await query<{ n: string }>(
    `SELECT COUNT(*)::text AS n FROM platform_users
     WHERE role = 'admin' AND status = 'approved' AND disabled_at IS NULL
       AND ($1::uuid IS NULL OR id <> $1::uuid)`,
    [excludeId ?? null]
  );
  return Number(rows[0]?.n ?? 0);
}
