import Link from "next/link";
import { PROJECTS } from "@/lib/projects";

/**
 * 作品集首页（M12 P5）——整个站的门面。
 * 公开可访问：访客不用登录就能看作品，登录只是为了进受保护的 RAG Coder。
 *
 * 展示哪些项目由 `lib/projects.ts` 决定，不在这里另立一份清单——两份清单迟早会分叉。
 * 带 `showcase` 的才进作品集：`/admin` 审核台是内部工具不是作品，它不写 showcase。
 */

/** 进作品集的项目：注册表里带 showcase 的那些，顺序即注册表顺序。 */
const WORKS = PROJECTS.filter((p) => p.showcase).map((p) => ({
  ...p.showcase!,
  href: p.route,
  /** 需登录+审核才能进——由访问级别推导，不再各自标记 */
  gated: p.access !== "public",
}));

export default function HomePage() {
  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-10 px-7 py-12">
      <section className="flex flex-col gap-3">
        <h1 className="text-[30px] font-semibold leading-none">peko</h1>
      </section>

      <section className="flex flex-col gap-4">
        <div className="flex items-center gap-2.5">
          <span className="block h-[9px] w-[9px] bg-accent" />
          <span className="text-[10px] tracking-label text-dim">WORKS · {WORKS.length}</span>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {WORKS.map((w) => (
            <article
              key={w.slug}
              className="flex flex-col border border-line bg-panel transition-shadow hover:shadow-[6px_6px_0_rgba(23,23,26,.06)]"
            >
              <div className="flex items-center gap-2.5 border-b border-line bg-shade px-4 py-2.5">
                <span className="block h-2 w-2 bg-accent" />
                <span className="text-[10px] tracking-label text-dim">
                  {w.slug.toUpperCase()}
                </span>
                <span className="ml-auto border border-line px-2 py-[2px] text-[9px] tracking-wide text-muted">
                  {w.status}
                </span>
              </div>

              <div className="flex flex-1 flex-col gap-4 p-5">
                <div className="flex flex-col gap-1">
                  <h2 className="text-[19px] font-semibold">{w.name}</h2>
                  <div className="text-[11px] tracking-wide text-accent">{w.tagline}</div>
                </div>

                <p className="text-[12px] leading-relaxed text-ink2">{w.body}</p>

                <ul className="flex flex-col gap-1.5 text-[11px] leading-relaxed text-muted">
                  {w.highlights.map((h) => (
                    <li key={h} className="flex gap-2">
                      <span className="mt-[6px] block h-[3px] w-[3px] flex-none bg-accent" />
                      <span>{h}</span>
                    </li>
                  ))}
                </ul>

                <div className="flex flex-wrap gap-1.5">
                  {w.stack.map((s) => (
                    <span
                      key={s}
                      className="border border-hair bg-shade px-1.5 py-[2px] text-[10px] text-ink2"
                    >
                      {s}
                    </span>
                  ))}
                </div>

                <div className="mt-auto flex items-center gap-2 pt-1">
                  <Link
                    href={w.href}
                    className="bg-ink px-4 py-2 text-[11px] font-medium tracking-wide text-paper"
                  >
                    进入 →
                  </Link>
                  {w.gated && (
                    <span className="text-[10px] leading-relaxed text-faint">
                      需 GitHub 登录并通过审核
                    </span>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

    </div>
  );
}
