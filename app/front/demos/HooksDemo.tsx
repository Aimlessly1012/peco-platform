"use client";

import { Fragment, useRef, useState } from "react";
import { Button, Input, Space } from "antd";
import {
  useAsyncFn,
  useCountDown,
  useDevicePixelRatio,
  useElementSize,
  useInView,
  useLocalStorage,
  usePolling,
  usePrevious,
  useWindowSize,
} from "heitu";
import { HOOK_COUNT, HOOK_GROUPS, type HookEntry } from "./hooks-reference";

/**
 * hooks demo：每组挑一到两个做可交互演示，其余在速查表里列全。
 * 19 个逐一做 demo 只会变成噪音，这里按「看得见效果」的优先。
 */

function Panel({
  title,
  hooks,
  children,
}: {
  title: string;
  hooks: string[];
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2.5 border border-line bg-panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12.5px] font-medium">{title}</span>
        {hooks.map((h) => (
          <code key={h} className="border border-hair bg-shade px-1.5 py-px text-[10px] text-accent">
            {h}
          </code>
        ))}
      </div>
      {children}
    </div>
  );
}

const Out = ({ children }: { children: React.ReactNode }) => (
  <div className="border border-hair bg-shade px-3 py-2 text-[11px] leading-relaxed text-ink2">
    {children}
  </div>
);

/** 假接口：随机延迟，偶尔失败，用来看 loading / error / value 三态。 */
const fakeFetch = (fail = false) =>
  new Promise<string>((resolve, reject) =>
    setTimeout(
      () => (fail ? reject(new Error("接口开小差了")) : resolve(`ok @ ${new Date().toLocaleTimeString()}`)),
      600
    )
  );

function AsyncPanel() {
  const [state, run] = useAsyncFn(async (fail?: boolean) => fakeFetch(!!fail), []);
  return (
    <Panel title="异步状态机" hooks={["useAsyncFn"]}>
      <Space>
        <Button type="primary" onClick={() => run(false)} loading={state.loading}>
          请求成功
        </Button>
        <Button danger onClick={() => run(true)} loading={state.loading}>
          请求失败
        </Button>
      </Space>
      <Out>
        {state.loading
          ? "loading…"
          : state.error
            ? `error: ${state.error.message}`
            : state.value
              ? `value: ${state.value}`
              : "未发起请求"}
      </Out>
    </Panel>
  );
}

function PollingPanel() {
  const [ticks, setTicks] = useState(0);
  const [running, setRunning] = useState(false);
  // manual 默认 false ——不显式设 true 的话，hook 一挂载就自己开始轮询了
  const polling = usePolling(
    async () => {
      setTicks((n) => n + 1);
      return Date.now();
    },
    { interval: 1000, manual: true }
  );
  return (
    <Panel title="轮询" hooks={["usePolling"]}>
      <Space>
        <Button
          type="primary"
          onClick={() => {
            polling.start();
            setRunning(true);
          }}
          disabled={running}
        >
          开始轮询
        </Button>
        <Button
          onClick={() => {
            polling.stop();
            setRunning(false);
          }}
          disabled={!running}
        >
          停止
        </Button>
      </Space>
      <Out>
        {running ? "轮询中" : "已停止"} · 已触发 {ticks} 次（间隔 1s）
      </Out>
    </Panel>
  );
}

function DomPanel() {
  const boxRef = useRef<HTMLDivElement>(null);
  const size = useElementSize(boxRef);
  const { pixelRatio } = useDevicePixelRatio();
  const [inViewRef, inView] = useInView();
  const [wide, setWide] = useState(false);

  return (
    <Panel
      title="尺寸与可见性"
      hooks={["useElementSize", "useDevicePixelRatio", "useInView"]}
    >
      <Space>
        <Button onClick={() => setWide((v) => !v)}>
          {wide ? "收窄容器" : "放宽容器"}
        </Button>
      </Space>
      <div
        ref={boxRef}
        className="border border-dashed border-line bg-shade px-3 py-4 text-[11px] text-muted transition-all"
        style={{ width: wide ? "100%" : "60%" }}
      >
        被观察的容器 · 拖动窗口或点上面的按钮看数值变化
      </div>
      <Out>
        element: {size.width} × {size.height} · DPR: {pixelRatio}
      </Out>

      <div className="mt-1 h-[92px] overflow-y-auto border border-hair bg-shade p-3">
        <div className="h-[120px] text-[11px] text-faint">↓ 往下滚，让下面的哨兵进入视口</div>
        <div
          ref={inViewRef as React.RefObject<HTMLDivElement>}
          className={`border px-3 py-2 text-[11px] ${
            inView ? "border-accent text-accent" : "border-line text-muted"
          }`}
        >
          {inView ? "哨兵已进入视口（useInView → true）" : "哨兵尚未进入视口"}
        </div>
        <div className="h-[60px]" />
      </div>
    </Panel>
  );
}

function StoragePanel() {
  const [note, setNote, removeNote] = useLocalStorage<string>("peko-front-demo", "");
  return (
    <Panel title="持久化" hooks={["useLocalStorage"]}>
      <Space.Compact style={{ width: "100%" }}>
        <Input
          value={note ?? ""}
          onChange={(e) => setNote(e.target.value)}
          placeholder="随便写点什么，刷新页面它还在"
        />
        <Button onClick={() => removeNote()}>清除</Button>
      </Space.Compact>
      <Out>localStorage[&quot;peko-front-demo&quot;] = {JSON.stringify(note ?? "")}</Out>
    </Panel>
  );
}

function CountDownPanel() {
  const [count, start, stop] = useCountDown();
  return (
    <Panel title="倒计时" hooks={["useCountDown"]}>
      <Space>
        <Button type="primary" disabled={count > 0} onClick={() => start(10)}>
          {count > 0 ? `${count}s 后可重发` : "发送验证码"}
        </Button>
        <Button onClick={() => stop()} disabled={count === 0}>
          中止
        </Button>
      </Space>
      <Out>count = {count}</Out>
    </Panel>
  );
}

function PreviousPanel() {
  const [n, setN] = useState(0);
  const prev = usePrevious(n);
  return (
    <Panel title="上一次的值" hooks={["usePrevious"]}>
      <Space>
        <Button onClick={() => setN((v) => v + 1)}>+1</Button>
        <Button onClick={() => setN((v) => v - 1)}>-1</Button>
      </Space>
      <Out>
        current = {n} · previous = {String(prev)} ·{" "}
        {prev === undefined ? "首次渲染" : n > prev ? "变大了" : n < prev ? "变小了" : "没变"}
      </Out>
    </Panel>
  );
}

function WindowPanel() {
  const win = useWindowSize();
  return (
    <Panel title="窗口尺寸" hooks={["useWindowSize"]}>
      <Out>
        window: {win.width} × {win.height} · 拖动浏览器窗口看数值跟随
      </Out>
    </Panel>
  );
}

export default function HooksDemo({ section }: { section: string }) {
  // 本组件由 /front 以 dynamic(ssr:false) 加载，整棵子树都不参与 SSR，
  // 所以 storage / window 这类 hook 不需要额外的 mounted 门禁
  const group = HOOK_GROUPS.find((g) => g.key === section);

  if (section === "all" || !group) {
    return <ApiTable />;
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[11px] leading-relaxed text-muted">
        {group.hint} · 本组共 {group.items.length} 个，其中带 DEMO 标记的在下面可以直接操作。
      </p>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {section === "async" && (
          <>
            <AsyncPanel />
            <PollingPanel />
          </>
        )}
        {section === "dom" && <DomPanel />}
        {section === "storage" && <StoragePanel />}
        {section === "interaction" && <CountDownPanel />}
        {section === "util" && (
          <>
            <PreviousPanel />
            <WindowPanel />
          </>
        )}
      </div>

      <section className="border border-line bg-panel">
        <div className="flex items-center gap-2.5 border-b border-line bg-shade px-4 py-2.5">
          <span className="block h-2 w-2 bg-accent" />
          <span className="text-[10px] tracking-label text-dim">
            {group.label.toUpperCase()} · {group.items.length} 个 API
          </span>
        </div>
        <HookRows items={group.items} />
      </section>
    </div>
  );
}

/** 一组 hook 的签名表格（组内视图与「全部 API」共用）。 */
function HookRows({ items }: { items: HookEntry[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-[12px]">
        <thead className="border-b border-line bg-shade text-left text-[10px] tracking-label text-dim">
          <tr>
            <th className="px-4 py-2.5 font-normal">HOOK</th>
            <th className="px-4 py-2.5 font-normal">签名</th>
            <th className="px-4 py-2.5 font-normal">说明</th>
          </tr>
        </thead>
        <tbody>
          {items.map((h) => (
            <tr key={h.name} className="border-b border-hair align-top last:border-b-0">
              <td className="whitespace-nowrap px-4 py-3">
                <code className="text-[11.5px] text-ink">{h.name}</code>
                {h.demo && (
                  <span className="ml-1.5 border border-accent/40 px-1 py-px text-[9px] tracking-wide text-accent">
                    DEMO
                  </span>
                )}
              </td>
              <td className="px-4 py-3">
                <code className="break-all text-[10.5px] leading-relaxed text-ink2">
                  {h.signature}
                </code>
              </td>
              <td className="px-4 py-3 leading-relaxed text-muted">{h.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 「全部 API」一节：19 个按组铺开。 */
function ApiTable() {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[11px] leading-relaxed text-muted">
        共 {HOOK_COUNT} 个 hook，签名取自安装版本的 .d.ts。带 DEMO 标记的可在左侧对应分组里直接操作。
      </p>
      <div className="border border-line">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-[12px]">
            <thead className="border-b border-line bg-shade text-left text-[10px] tracking-label text-dim">
              <tr>
                <th className="px-4 py-2.5 font-normal">HOOK</th>
                <th className="px-4 py-2.5 font-normal">签名</th>
                <th className="px-4 py-2.5 font-normal">说明</th>
              </tr>
            </thead>
            <tbody>
              {HOOK_GROUPS.map((g) => (
                // 匿名 <> 不接受 key，必须写成 <Fragment key=...>
                <Fragment key={g.key}>
                  <tr className="border-b border-hair bg-shade/60">
                    <td colSpan={3} className="px-4 py-2">
                      <span className="text-[10px] tracking-label text-dim">
                        {g.label.toUpperCase()}
                      </span>
                      <span className="ml-2 text-[10px] text-faint">{g.hint}</span>
                    </td>
                  </tr>
                  {g.items.map((h) => (
                    <tr key={h.name} className="border-b border-hair align-top last:border-b-0">
                      <td className="whitespace-nowrap px-4 py-3">
                        <code className="text-[11.5px] text-ink">{h.name}</code>
                        {h.demo && (
                          <span className="ml-1.5 border border-accent/40 px-1 py-px text-[9px] tracking-wide text-accent">
                            DEMO
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <code className="break-all text-[10.5px] leading-relaxed text-ink2">
                          {h.signature}
                        </code>
                      </td>
                      <td className="px-4 py-3 leading-relaxed text-muted">{h.desc}</td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
