import { getServerSession } from "next-auth";
import { authOptions } from "./auth";
import type { UserRole, UserStatus } from "./users";

export interface SessionUser {
  id: string;
  githubId: string;
  name: string;
  role: UserRole;
  status: UserStatus;
  disabled: boolean;
}

/** 取当前登录用户（服务端）。未登录返回 null。 */
export async function currentUser(): Promise<SessionUser | null> {
  const session = await getServerSession(authOptions);
  const u = session?.user;
  if (!u?.githubId) return null;
  return {
    id: u.id,
    githubId: u.githubId,
    name: u.name,
    role: u.role,
    status: u.status,
    disabled: u.disabled,
  };
}

export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string
  ) {
    super(message);
  }
}

/** 要求已登录、已批准、未禁用。 */
export async function requireActiveUser(): Promise<SessionUser> {
  const u = await currentUser();
  if (!u) throw new HttpError(401, "请先登录");
  if (u.disabled) throw new HttpError(403, "账号已被禁用");
  if (u.status !== "approved") throw new HttpError(403, "账号尚未通过审核");
  return u;
}

export async function requireAdmin(): Promise<SessionUser> {
  const u = await requireActiveUser();
  if (u.role !== "admin") throw new HttpError(403, "需要管理员权限");
  return u;
}
