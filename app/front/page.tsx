"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import AntdTerminalTheme from "@/components/AntdTerminalTheme";

/**
 * heitu 组件库展示（M12 P6）。
 *
 * demo 全部 ssr:false：charts 是 canvas 自绘、antd 组件也大量依赖浏览器 API，
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

const TABS = [
  { key: "form", label: "FormRender" },
  { key: "charts", label: "Charts" },
  { key: "canvas", label: "Canvas 引擎" },
  { key: "hooks", label: "Hooks" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const INSTALL = "npm install heitu antd";

export default function FrontPage() {
  const [tab, setTab] = useState<TabKey>("form");

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-[212px] flex-none flex-col gap-7 overflow-y-auto border-r border-line bg-canvas px-5 py-6 md:flex">
        <div className="flex flex-col gap-1.5">
          <div className="text-[10px] tracking-label text-dim">HEITU</div>
          <div className="text-[26px] font-semibold leading-none">v1.1.0</div>
          <div className="text-[11px] text-muted">npm 已发布</div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[10px] tracking-label text-dim">INSTALL</div>
          <code className="break-all border border-line bg-shade px-2 py-1.5 text-[10.5px] leading-relaxed text-ink2">
            {INSTALL}
          </code>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[10px] tracking-label text-dim">ENTRIES</div>
          <ul className="flex flex-col gap-1 text-[11px] text-muted">
            {["heitu", "heitu/hooks", "heitu/components", "heitu/charts", "heitu/canvas"].map(
              (e) => (
                <li key={e} className="break-all">
                  {e}
                </li>
              )
            )}
          </ul>
        </div>

        <div className="mt-auto text-[11px] leading-relaxed text-faint">
          antd 经 ConfigProvider
          <br />
          <span className="text-muted">适配终端风令牌</span>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-7 py-6">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[22px] font-semibold">heitu 组件库</h1>
          <span className="text-[11px] text-dim">
            $ import from &apos;heitu&apos;<span className="text-accent">_</span>
          </span>
        </div>

        <p className="max-w-3xl text-[12px] leading-relaxed text-muted">
          自研 React 工具库：JSON 配置驱动的表单渲染器、canvas 自绘图表、以及一组通用 hooks。
          下面的 demo 都是真实组件，可以直接操作。antd 的主色、圆角与字体已通过 ConfigProvider
          对齐本站令牌——同一套组件，换了皮就不违和。
        </p>

        <div className="flex gap-0 border-b border-line" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={`-mb-px border-b-2 px-4 py-2 text-[11.5px] tracking-wide ${
                tab === t.key
                  ? "border-accent font-medium text-ink"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <section className="border border-line bg-panel">
          <div className="flex items-center gap-2.5 border-b border-line bg-shade px-4 py-2.5">
            <span className="block h-2 w-2 bg-accent" />
            <span className="text-[10px] tracking-label text-dim">
              {
                {
                  form: "FORM RENDER · 配置即表单",
                  charts: "CHARTS · canvas 自绘 · 4 种图表",
                  canvas: "CANVAS ENGINE · 图元 / 命中检测 / 补间动画",
                  hooks: "HOOKS · 19 个，按类别归组",
                }[tab]
              }
            </span>
          </div>
          <div className="p-5">
            <AntdTerminalTheme>
              {tab === "form" && <FormRenderDemo />}
              {tab === "charts" && <ChartsDemo />}
              {tab === "canvas" && <CanvasDemo />}
              {tab === "hooks" && <HooksDemo />}
            </AntdTerminalTheme>
          </div>
        </section>

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
            <li>
              <span className="text-accent">·</span> antd 是 peer 依赖；本页用 ConfigProvider
              注入终端风 token（主色 #0e7a45、圆角 0、IBM Plex Mono）。
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
