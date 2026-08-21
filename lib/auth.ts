import { SignJWT, jwtVerify } from "jose";
import type { NextAuthOptions } from "next-auth";
import GitHubProvider from "next-auth/providers/github";
import { getByGithubId, upsertOnLogin, type UserRole, type UserStatus } from "./users";

/**
 * NextAuth 配置（M12 P2）。
 *
 * JWT strategy + **jwt 回调每次查库取最新 status**：审核制的分水岭就在这里。
 * 如果只在登录时把 status 塞进 token，管理员批准/禁用后要等 token 过期（默认 30 天）
 * 才生效，审核等于没有。代价是每次带 token 的请求多一次主键查询，个人站规模无所谓。
 */

declare module "next-auth" {
  interface Session {
    user: {
      id: string;
      githubId: string;
      name: string;
      image: string | null;
      role: UserRole;
      status: UserStatus;
      disabled: boolean;
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    uid?: string;
    githubId?: string;
    role?: UserRole;
    status?: UserStatus;
    disabled?: boolean;
  }
}

export const authOptions: NextAuthOptions = {
  providers: [
    GitHubProvider({
      clientId: process.env.GITHUB_ID ?? "",
      clientSecret: process.env.GITHUB_SECRET ?? "",
    }),
  ],
  session: { strategy: "jwt" },

  /**
   * 把 NextAuth 默认的 JWE（加密）换成 JWS（HS256 签名）。
   *
   * 这是跨服务鉴权的关键约定：RAG 的 FastAPI 后端用同一个密钥（AUTH_JWT_SECRET）
   * 直接验签这个 cookie，从而不需要在平台加一层 API 代理——那层代理要转发 SSE
   * 流式与 MCP 长连接，风险远大于收益（见 design.md D2）。
   *
   * 代价：token 内容可被解码查看（但不可篡改）。里面只有 githubId/role/status，
   * 不含密钥或隐私，可接受。
   */
  jwt: {
    async encode({ token, secret, maxAge }) {
      const key = new TextEncoder().encode(String(secret));
      const now = Math.floor(Date.now() / 1000);
      return await new SignJWT({ ...token })
        .setProtectedHeader({ alg: "HS256" })
        .setIssuedAt(now)
        .setExpirationTime(now + (maxAge ?? 30 * 24 * 60 * 60))
        .sign(key);
    },
    async decode({ token, secret }) {
      if (!token) return null;
      try {
        const key = new TextEncoder().encode(String(secret));
        const { payload } = await jwtVerify(token, key, { algorithms: ["HS256"] });
        return payload as Record<string, unknown>;
      } catch {
        // 过期或被篡改：当作未登录，让 NextAuth 走重新登录流程
        return null;
      }
    },
  },
  pages: {
    signIn: "/login",
    error: "/login",
  },
  callbacks: {
    async jwt({ token, account, profile }) {
      // 首次登录（拿得到 GitHub profile）：upsert，新人落 pending
      if (account && profile) {
        const gh = profile as { id?: number | string; login?: string; name?: string; avatar_url?: string };
        const githubId = String(gh.id ?? "");
        if (githubId) {
          const user = await upsertOnLogin({
            githubId,
            name: gh.name || gh.login || githubId,
            avatarUrl: gh.avatar_url ?? null,
          });
          token.uid = user.id;
          token.githubId = user.github_id;
          token.name = user.name;
          token.picture = user.avatar_url ?? undefined;
        }
      }

      // 之后每次都回库取最新状态——审批/禁用要立刻生效
      if (token.githubId) {
        try {
          const fresh = await getByGithubId(token.githubId);
          if (fresh) {
            token.uid = fresh.id;
            token.role = fresh.role;
            token.status = fresh.status;
            token.disabled = !!fresh.disabled_at;
            token.name = fresh.name;
            token.picture = fresh.avatar_url ?? undefined;
          } else {
            // 记录被删了：按未授权处理，别沿用旧 token 里的状态
            token.role = "member";
            token.status = "rejected";
            token.disabled = true;
          }
        } catch {
          // 库连不上时保守处理：不放行。宁可让人重登，也不要把禁用过的人放进来
          token.status = "pending";
          token.disabled = true;
        }
      }
      return token;
    },

    async session({ session, token }) {
      session.user = {
        id: token.uid ?? "",
        githubId: token.githubId ?? "",
        name: (token.name as string) ?? "",
        image: (token.picture as string) ?? null,
        role: token.role ?? "member",
        status: token.status ?? "pending",
        disabled: token.disabled ?? false,
      };
      return session;
    },
  },
};
