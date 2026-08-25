"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import AntdTerminalTheme from "@/components/AntdTerminalTheme";
import { TABS, tabByKey, type TabKey } from "./nav";

/**
 * heitu 组件库展示（M12 P6 + 信息架构改造）。
 *
 * 两级导航：顶部 tab 分大类，左侧栏是当前 tab 的子项——原先子项塞在内容区里
 * （Charts 用 Segmented、Hooks 用 chips），和大类挤在同一块，层级看不出来。
 *
 * demo 全部 ssr:false：charts / canvas 是 canvas 自绘、antd 组件也大量依赖浏览器 API，
 * 关掉 SSR 既省掉样式闪烁，也不用引 @ant-design/nextjs-registry 那套 SSR 样式提取。
 */

function loading(label: string) {
  const Loading = () => (
    <div className="border border-line bg-panel px-4 py-16 text-center text-[11px] tracking-wide text-faint">
      {label}
    </div>
  );
  Loading.displayName = `Loading(${label})`;
  return Loading;
}

const FormRenderDemo = dynamic(() => import("./demos/FormRenderDemo"), {
  ssr: false,
  loading: loading("LOADING FORM DEMO…"),
});

const ChartsDemo = dynamic(() => import("./demos/ChartsDemo"), {
  ssr: false,
  loading: loading("LOADING CHART DEMO…"),
});

const CanvasDemo = dynamic(() => import("./demos/CanvasDemo"), {
  ssr: false,
  loading: loading("LOADING CANVAS DEMO…"),
});

const HooksDemo = dynamic(() => import("./demos/HooksDemo"), {
  ssr: false,
  loading: loading("LOADING HOOKS DEMO…"),
});

const AI_SKILLS = [
  { name: "heitu-formrender", desc: "JSON 驱动表单：配置、联动、异步选项、自定义控件" },
  { name: "heitu-charts", desc: "四种图表 props 速查 + 宽度陷阱、动画遮罩等实机坑位" },
  { name: "heitu-canvas", desc: "Stage/图元/事件/Animate 全流程与 1.1.x 版本差异" },
  { name: "heitu-hooks", desc: "19 个 hooks 签名速查与容易踩的语义细节" },
];

const INSTALL = "npm install heitu antd";

export default function FrontPage() {
  /** null = 停在第一层（大类列表）；选中某个大类后才进第二层。 */
  const [tab, setTab] = useState<TabKey | null>(null);
  const [section, setSection] = useState<string>("");
  const current = tab ? tabByKey(tab) : null;

  /** 进入某个大类：侧栏换成它的子项，内容默认落在第一项。 */
  const enterTab = (key: TabKey) => {
    setTab(key);
    setSection(tabByKey(key).sections[0].key);
  };

  /** 返回第一层。 */
  const goRoot = () => {
    setTab(null);
    setSection("");
  };

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左栏：品牌信息 + 当前 tab 的子项导航 */}
      <aside className="hidden w-[212px] flex-none flex-col gap-6 overflow-y-auto border-r border-line bg-canvas px-5 py-6 md:flex">
        <div className="flex flex-col gap-1.5">
          <div className="text-[10px] tracking-label text-dim">HEITU</div>
          <div className="text-[26px] font-semibold leading-none">v1.1.1</div>
          <div className="text-[11px] text-muted">npm 已发布</div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[10px] tracking-label text-dim">INSTALL</div>
          <code className="break-all border border-line bg-shade px-2 py-1.5 text-[10.5px] leading-relaxed text-ink2">
            {INSTALL}
          </code>
        </div>

        {/* 逐层钻取：第一层只列大类，进去后换成子项并给出返回入口 */}
        {current === null ? (
          <nav className="flex flex-col gap-1.5" aria-label="模块">
            <div className="text-[10px] tracking-label text-dim">MODULES</div>
            <div className="flex flex-col">
              {TABS.map((t2) => (
                <button
                  key={t2.key}
                  type="button"
                  onClick={() => enterTab(t2.key)}
                  className="flex items-center gap-2 border-l-2 border-transparent px-3 py-2 text-left transition-colors hover:bg-panel/60"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block text-[12px] text-ink">{t2.label}</span>
                    <span className="mt-0.5 block text-[10px] leading-relaxed text-faint">
                      {t2.sections.length} 项
                    </span>
                  </span>
                  <span className="text-[11px] text-faint">›</span>
                </button>
              ))}
            </div>
          </nav>
        ) : (
          <nav className="flex flex-col gap-1.5" aria-label={`${current.label} 子项`}>
            <button
              type="button"
              onClick={goRoot}
              className="flex items-center gap-1.5 self-start text-[11px] text-muted transition-colors hover:text-ink"
            >
              <span aria-hidden>←</span> 返回
            </button>
            <div className="text-[10px] tracking-label text-dim">
              {current.label.toUpperCase()}
            </div>
            <div className="flex flex-col">
              {current.sections.map((s) => {
                const on = s.key === section;
                return (
                  <button
                    key={s.key}
                    type="button"
                    onClick={() => setSection(s.key)}
                    aria-current={on ? "true" : undefined}
                    className={`border-l-2 px-3 py-2 text-left transition-colors ${
                      on
                        ? "border-accent bg-panel"
                        : "border-transparent hover:bg-panel/60"
                    }`}
                  >
                    <span
                      className={`block text-[12px] ${on ? "font-medium text-ink" : "text-muted"}`}
                    >
                      {s.label}
                    </span>
                    <span
                      className={`mt-0.5 block text-[10px] leading-relaxed ${
                        on ? "text-dim" : "text-faint"
                      }`}
                    >
                      {s.hint}
                    </span>
                  </button>
                );
              })}
            </div>
          </nav>
        )}

        <div className="mt-auto text-[11px] leading-relaxed text-faint">
          antd 经 ConfigProvider
          <br />
          <span className="text-muted">适配终端风令牌</span>
        </div>
      </aside>

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-7 py-6">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[22px] font-semibold">heitu 组件库</h1>
          <span className="text-[11px] text-dim">
            $ import from &apos;heitu&apos;<span className="text-accent">_</span>
          </span>
        </div>

        <p className="max-w-3xl text-[12px] leading-relaxed text-muted">
          自研 React 工具库：JSON 配置驱动的表单渲染器、canvas 自绘图表与引擎、以及一组通用 hooks。
          下面的 demo 都是真实组件，可以直接操作。antd 的主色、圆角与字体已通过 ConfigProvider
          对齐本站令牌——同一套组件，换了皮就不违和。
        </p>

        {current === null ? (
          /* 第一层：大类概览。既是导航入口也是介绍，比空白页有用 */
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {TABS.map((t2) => (
                <button
                  key={t2.key}
                  type="button"
                  onClick={() => enterTab(t2.key)}
                  className="border border-line bg-panel p-4 text-left transition-colors hover:border-ink"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="block h-2 w-2 bg-accent" />
                    <span className="text-[13px] font-medium">{t2.label}</span>
                    <span className="ml-auto text-[10px] tracking-wide text-faint">
                      {t2.sections.length} 项 →
                    </span>
                  </div>
                  <ul className="mt-2.5 flex flex-col gap-1">
                    {t2.sections.map((s) => (
                      <li key={s.key} className="text-[11px] leading-relaxed text-muted">
                        <span className="text-faint">·</span> {s.label}
                        <span className="ml-1.5 text-faint">{s.hint}</span>
                      </li>
                    ))}
                  </ul>
                </button>
              ))}
            </div>

            {/* npm 包内置的 AI skill 文档：装包即让 Claude Code 学会正确用法，作品集亮点 */}
            <section className="border border-line bg-panel p-4">
              <div className="flex items-baseline gap-2">
                <span className="block h-2 w-2 bg-accent" />
                <span className="text-[10px] tracking-label text-dim">AI SKILLS</span>
                <span className="ml-auto text-[10px] tracking-wide text-faint">
                  npm 包内置 · 安装即生效
                </span>
              </div>
              <p className="mt-2.5 text-[11px] leading-relaxed text-muted">
                包里自带 <code>.claude/skills/</code> 四份技能文档——
                <code>npm install heitu</code> 之后，Claude Code 等 AI 编码工具无需翻源码，
                直接掌握各组件的正确入口、参数与实机坑位：
              </p>
              <ul className="mt-2.5 grid grid-cols-1 gap-1.5 text-[11px] leading-relaxed text-muted sm:grid-cols-2">
                {AI_SKILLS.map((s) => (
                  <li key={s.name}>
                    <code className="text-accent">{s.name}</code>
                    <span className="ml-1.5">{s.desc}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2.5 text-[10.5px] leading-relaxed text-faint">
                内容按 TDD 方式维护：先让不带 skill 的 AI 实测踩坑（基线），再对照验证带
                skill 后坑位全部规避，才随包发布。
              </p>
            </section>
          </>
        ) : (
          <>
            {/* 面包屑：第二层里始终看得见自己在哪、怎么回去 */}
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <button
                type="button"
                onClick={goRoot}
                className="text-muted transition-colors hover:text-ink"
              >
                ← 全部模块
              </button>
              <span className="text-faint">/</span>
              <span className="text-ink">{current.label}</span>
              <span className="text-faint">/</span>
              <span className="text-dim">
                {current.sections.find((s) => s.key === section)?.label}
              </span>
            </div>

            {/* 窄屏没有侧栏，子项退化成横向 chips */}
            <div className="flex flex-wrap gap-1.5 md:hidden">
              {current.sections.map((s) => {
                const on = s.key === section;
                return (
                  <button
                    key={s.key}
                    type="button"
                    onClick={() => setSection(s.key)}
                    className={`border px-2.5 py-1 text-[11px] ${
                      on
                        ? "border-accent bg-accent/[.08] text-accent"
                        : "border-line text-muted hover:border-ink hover:text-ink"
                    }`}
                  >
                    {s.label}
                  </button>
                );
              })}
            </div>

            <section className="border border-line bg-panel">
              <div className="flex flex-wrap items-center gap-2.5 border-b border-line bg-shade px-4 py-2.5">
                <span className="block h-2 w-2 bg-accent" />
                <span className="text-[10px] tracking-label text-dim">{current.caption}</span>
                <span className="ml-auto text-[10px] tracking-wide text-faint">
                  {current.sections.find((s) => s.key === section)?.hint}
                </span>
              </div>
              <div className="p-5">
                <AntdTerminalTheme>
                  {tab === "form" && <FormRenderDemo section={section} />}
                  {tab === "charts" && <ChartsDemo section={section} />}
                  {tab === "canvas" && <CanvasDemo section={section} />}
                  {tab === "hooks" && <HooksDemo section={section} />}
                </AntdTerminalTheme>
              </div>
            </section>
          </>
        )}

        <section className="border border-line bg-panel p-4">
          <div className="text-[10px] tracking-label text-dim">NOTES</div>
          <ul className="mt-2.5 flex flex-col gap-1.5 text-[11px] leading-relaxed text-muted">
            <li>
              <span className="text-accent">·</span> FormRender 的 <code>config</code> 支持二维数组
              （一行多项）、<code>divider</code> 分组、<code>watch</code> 字段联动与{" "}
              <code>service</code> 异步选项。
            </li>
            <li>
              <span className="text-accent">·</span> charts 直接操作 canvas，没有引入 G2/ECharts
              这类重型依赖，包体积可控；四种图表含双轴柱线图。
            </li>
            <li>
              <span className="text-accent">·</span> canvas 引擎是 charts 的底座：Stage 分层、
              Rect / Circle / Line / Text / Group / Custom 六种图元、命中检测、拖拽与
              Animate 补间，可脱离图表单独用。
            </li>
            <li>
              <span className="text-accent">·</span> hooks 共 19 个，覆盖数据请求、DOM 观察、
              存储、交互与工具五类，均可从 <code>heitu/hooks</code> 按需引入。
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
