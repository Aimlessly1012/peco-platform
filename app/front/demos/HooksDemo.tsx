"use client";

import { Fragment, useRef, useState } from "react";
import { Button, Input, Space, Tag } from "antd";
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
import { HOOK_COUNT, HOOK_GROUPS } from "./hooks-reference";

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
  const win = useWindowSize();
  const [inViewRef, inView] = useInView();
  const [wide, setWide] = useState(false);

  return (
    <Panel
      title="尺寸与可见性"
      hooks={["useElementSize", "useDevicePixelRatio", "useWindowSize", "useInView"]}
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
        element: {size.width} × {size.height} · window: {win.width} × {win.height} · DPR: {pixelRatio}
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
  const [note, setNote, removeNote] = useLocalStorage<string>("peco-front-demo", "");
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
      <Out>localStorage[&quot;peco-front-demo&quot;] = {JSON.stringify(note ?? "")}</Out>
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

export default function HooksDemo() {
  // 本组件由 /front 以 dynamic(ssr:false) 加载，整棵子树都不参与 SSR，
  // 所以 storage / window 这类 hook 不需要额外的 mounted 门禁
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
        <span>共 {HOOK_COUNT} 个 hook，下面挑了 9 个做可交互演示：</span>
        <Tag color="green">数据请求</Tag>
        <Tag>DOM 观察</Tag>
        <Tag>存储</Tag>
        <Tag>交互</Tag>
        <Tag>工具</Tag>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <AsyncPanel />
        <PollingPanel />
        <DomPanel />
        <StoragePanel />
        <CountDownPanel />
        <PreviousPanel />
      </div>

      <section className="border border-line bg-panel">
        <div className="flex items-center gap-2.5 border-b border-line bg-shade px-4 py-2.5">
          <span className="block h-2 w-2 bg-accent" />
          <span className="text-[10px] tracking-label text-dim">API 速查 · {HOOK_COUNT}</span>
        </div>
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
                // key 要挂在 map 直接返回的那个元素上。这里返回的是片段，
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
      </section>
    </div>
  );
}
