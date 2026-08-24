import { decodeSessionToken } from "@/lib/jwt";
import { withAuth } from "next-auth/middleware";
import { NextResponse } from "next/server";

/**
 * 受保护路由的第一道门（M12 P4）。
 *
 * 跑在 edge runtime，**不能查库**（pg 进不去），但也不需要——jwt 回调每次登录态刷新时
 * 已经把最新 status/role 写进 token 了，这里只读 token 判断即可。
 * 页面与 API 各自还有第二道校验，这层只是让人不必先看到页面再被弹走。
 */
export default withAuth(
  function middleware(req) {
    const token = req.nextauth.token;
    const { pathname } = req.nextUrl;

    // 没通过审核 / 被禁用 → 送去状态页
    if (token?.status !== "approved" || token?.disabled) {
      return NextResponse.redirect(new URL("/pending", req.url));
    }
    // 审核页只给管理员
    if (pathname.startsWith("/admin") && token?.role !== "admin") {
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

export const config = {
  // /rag 是阶段二迁入的 RAG 页面，先把守卫挂上
  // "/rag/:path*" 只匹配 /rag/xxx，**匹配不到 /rag 裸路径**（Next 的经典坑，
  // 实测未登录访问 /rag 直接放行）。两条都列出来才盖全
  matcher: ["/admin", "/admin/:path*", "/rag", "/rag/:path*"],
};
