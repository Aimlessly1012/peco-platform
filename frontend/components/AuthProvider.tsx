"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { authApi, AuthUser, setUnauthorizedHandler } from "@/lib/api";
import { loginHref, LOGIN_PATH, safeNext } from "@/lib/nav";

export { LOGIN_PATH, safeNext };

/**
 * 登录态探测与全站守卫（M8）。
 *
 * 登录态是 httpOnly cookie，前端读不到也不该读，只能靠 GET /auth/me 探测。
 * 守卫在这里做而不是 middleware：cookie 校验要打后端，middleware 里做等于每次
 * 导航多一跳；而且 basePath 形态下跳转必须走 router 才带得上前缀。
 */

type Status = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  user: AuthUser | null;
  status: Status;
  isAdmin: boolean;
  /** 登录/注册成功后由登录页调用，直接写入已知用户，省一次 /auth/me。 */
  setUser: (user: AuthUser) => void;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}

export default function AuthProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const [user, setUserState] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  // 跳转是异步的，用 ref 挡住这期间重复触发的 401
  const redirecting = useRef(false);
  const onLoginPage = pathname === LOGIN_PATH;

  const refresh = useCallback(async () => {
    try {
      const me = await authApi.me();
      setUserState(me);
      setStatus("authenticated");
      redirecting.current = false;
    } catch {
      setUserState(null);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // 业务请求拿到 401（cookie 过期等）时，由 api 层通知到这里统一跳登录
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUserState(null);
      setStatus("anonymous");
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    if (status !== "anonymous" || onLoginPage || redirecting.current) return;
    redirecting.current = true;
    const query =
      typeof window === "undefined" ? "" : window.location.search;
    router.replace(loginHref(`${pathname}${query}`));
  }, [status, onLoginPage, pathname, router]);

  const setUser = useCallback((next: AuthUser) => {
    setUserState(next);
    setStatus("authenticated");
    redirecting.current = false;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      /* 无论后端结果如何，本地都按已登出处理 */
    }
    setUserState(null);
    setStatus("anonymous");
    redirecting.current = true;
    router.replace(LOGIN_PATH);
  }, [router]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      isAdmin: user?.role === "admin",
      setUser,
      logout,
      refresh,
    }),
    [user, status, setUser, logout, refresh]
  );

  // 登录页自己不受守卫管辖，否则会和跳转互相触发
  const gate =
    onLoginPage || status === "authenticated" ? (
      children
    ) : (
      // 占位直接铺满视口：此时 AppShell（含顶栏）整个不渲染，业务页也不会发请求
      <div className="flex h-screen items-center justify-center text-[11px] tracking-wide text-faint">
        {status === "loading" ? "CHECKING SESSION…" : "REDIRECTING TO LOGIN…"}
      </div>
    );

  return <AuthContext.Provider value={value}>{gate}</AuthContext.Provider>;
}
