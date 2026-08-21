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
