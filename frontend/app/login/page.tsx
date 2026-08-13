"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { safeNext, useAuth } from "@/components/AuthProvider";
import { ApiError, authApi } from "@/lib/api";

type Tab = "login" | "register";

const TABS: { key: Tab; label: string }[] = [
  { key: "login", label: "登录" },
  { key: "register", label: "注册" },
];

const FIELD =
  "w-full border border-line bg-shade px-3 py-2 text-[12.5px] focus:border-accent focus:bg-panel";
const LABEL = "text-[10px] tracking-wide text-dim";

export default function LoginPage() {
  const router = useRouter();
  const { status, setUser } = useAuth();
  const [tab, setTab] = useState<Tab>("login");
  const [form, setForm] = useState({
    username: "",
    password: "",
    invite_code: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  /** 回跳地址：用 window.location 读而不是 useSearchParams，省一层 Suspense 边界。 */
  const [next, setNext] = useState("/");

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    setNext(safeNext(q.get("next")));
  }, []);

  // 已经登录了还停在登录页（比如手动输地址）：直接送走
  useEffect(() => {
    if (status === "authenticated") router.replace(next);
  }, [status, next, router]);

  const submit = async () => {
    const username = form.username.trim();
    const password = form.password;
    const invite = form.invite_code.trim();

    if (!username || !password) {
      setError("用户名和密码必填");
      return;
    }
    if (tab === "register" && !invite) {
      setError("注册需要邀请码");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const user =
        tab === "login"
          ? await authApi.login(username, password)
          : await authApi.register(username, password, invite);
      setUser(user);
      router.replace(next);
    } catch (e) {
      // 后端对登录失败统一回 401「用户名或密码不正确」，直接透传它的措辞
      setError(
        e instanceof ApiError
          ? e.message
          : (e as Error).message || "请求失败，请稍后再试"
      );
      setSubmitting(false);
    }
  };

  const switchTab = (key: Tab) => {
    setTab(key);
    setError("");
  };

  return (
    <div className="flex h-full flex-1 items-center justify-center px-4">
      <div className="w-full max-w-[420px]">
        <div className="mb-6 flex items-center gap-[9px]">
          <span className="block h-[9px] w-[9px] bg-accent" />
          <span className="text-sm font-semibold tracking-wide">RAG&nbsp;CODER</span>
          <span className="text-[11px] text-dim">
            $ auth<span className="text-accent">_</span>
          </span>
        </div>

        <div className="border border-ink bg-panel shadow-[8px_8px_0_rgba(23,23,26,.07)]">
          <div className="flex border-b border-line bg-shade" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                onClick={() => switchTab(t.key)}
                className={`-mb-px border-b-2 px-5 py-2.5 text-[11.5px] tracking-wide ${
                  tab === t.key
                    ? "border-accent font-medium text-ink"
                    : "border-transparent text-muted hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <form
            className="flex flex-col gap-[15px] px-[26px] py-6"
            onSubmit={(e) => {
              e.preventDefault();
              if (!submitting) submit();
            }}
          >
            <div className="flex flex-col gap-1.5">
              <span className={LABEL}>
                USERNAME <span className="text-accent">*</span>
              </span>
              <input
                className={FIELD}
                autoComplete="username"
                autoFocus
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <span className={LABEL}>
                PASSWORD <span className="text-accent">*</span>
              </span>
              <input
                className={FIELD}
                type="password"
                autoComplete={tab === "login" ? "current-password" : "new-password"}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </div>

            {tab === "register" && (
              <div className="flex flex-col gap-1.5">
                <span className={LABEL}>
                  INVITE CODE <span className="text-accent">*</span>
                </span>
                <input
                  className={FIELD}
                  placeholder="管理员发放的一次性邀请码"
                  value={form.invite_code}
                  onChange={(e) => setForm({ ...form, invite_code: e.target.value })}
                />
              </div>
            )}

            {error && (
              <div className="border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-[11px] leading-relaxed text-danger">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="mt-1 bg-ink px-4 py-[9px] text-[11px] font-medium tracking-wide text-paper disabled:opacity-50"
            >
              {submitting
                ? tab === "login"
                  ? "登录中…"
                  : "注册中…"
                : tab === "login"
                  ? "登录"
                  : "注册并登录"}
            </button>

            <p className="text-[10px] leading-relaxed text-faint">
              {tab === "login"
                ? "没有账号？切到「注册」，用管理员发的邀请码开通。"
                : "邀请码一次性使用，注册成功后自动登录。"}
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
