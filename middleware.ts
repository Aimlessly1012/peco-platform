import { decodeSessionToken } from "@/lib/jwt";
import { projectOf } from "@/lib/projects";
import { withAuth } from "next-auth/middleware";
import { NextResponse } from "next/server";

/**
 * 受保护路由的第一道门（M12 P4）。
 *
 * 跑在 edge runtime，**不能查库**（pg 进不去），但也不需要——jwt 回调每次登录态刷新时
 * 已经把最新 status/role 写进 token 了，这里只读 token 判断即可。
 * 页面与 API 各自还有第二道校验，这层只是让人不必先看到页面再被弹走。
 *
 * 判断逻辑读 `lib/projects.ts` 的注册表，新增项目不必在这里加分支；
 * 但下面的 `config.matcher` 必须是静态字面量（Next 的限制），生成不了，
 * 只能手写 + `npm run check:middleware` 盯着。
 */
export default withAuth(
  function middleware(req) {
    const token = req.nextauth.token;
    const { pathname } = req.nextUrl;
    const project = projectOf(pathname);

    // matcher 只挂受保护项目，理论上必然命中；命中不到说明 matcher 与注册表脱节，
    // 那属于配置错误而不是访问控制问题——放行交给页面与 API 的第二道校验，
    // 真正的拦截由 check:middleware 在 CI 上完成。
    if (!project || project.access === "public") {
      return NextResponse.next();
    }

    // 没通过审核 / 被禁用 → 送去状态页
    if (token?.status !== "approved" || token?.disabled) {
      return NextResponse.redirect(new URL("/pending", req.url));
    }
    // admin 级项目追加管理员校验
    if (project.access === "admin" && token?.role !== "admin") {
      return NextResponse.redirect(new URL("/", req.url));
    }
    return NextResponse.next();
  },
  {
    pages: { signIn: "/login" },
    // **必须显式传自定义 decode**：withAuth 内部默认按 JWE 解，而我们的会话
    // token 是 JWS(HS256)（lib/jwt.ts，后端验签需要）。不传的话这里永远解出
    // null——已登录用户访问 /rag、/admin 会被当成未登录踢回登录页（实测踩过）。
    jwt: { decode: decodeSessionToken },
    // 没有 token 的一律先去登录页（withAuth 自动带 callbackUrl 回跳）
    callbacks: { authorized: ({ token }) => !!token },
  }
);

// ⚠️ 每个非 public 项目都要两条：裸路径 + `:path*`。
// `"/rag/:path*"` **匹配不到 `/rag` 裸路径**（Next 的经典坑，commit 6eaef3d 实测
// 未登录访问 /rag 直接放行）。这里无法从注册表生成——Next 要求 matcher 是静态字面量，
// 所以由 `npm run check:middleware` 比对注册表，缺任一条即非零退出。
export const config = {
  matcher: ["/admin", "/admin/:path*", "/rag", "/rag/:path*"],
};
