"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Segmented } from "antd";
import {
  BarChartComponent,
  LineChartComponent,
  PieChartComponent,
} from "heitu";

/**
 * charts demo：canvas 自绘，不依赖重型图表库。
 * 配色传的是终端风令牌，跟站里其他图表口径一致。
 */

const PALETTE = ["#0e7a45", "#4a4842", "#8a8880", "#b8422f", "#d9d7cf"];

type Kind = "line" | "bar" | "pie";

const TREND = [
  { month: "1月", indexed: 4, chats: 12 },
  { month: "2月", indexed: 7, chats: 31 },
  { month: "3月", indexed: 6, chats: 44 },
  { month: "4月", indexed: 11, chats: 68 },
  { month: "5月", indexed: 9, chats: 91 },
  { month: "6月", indexed: 14, chats: 120 },
];

const LANGS = [
  { lang: "TypeScript", files: 486 },
  { lang: "Python", files: 312 },
  { lang: "Vue", files: 174 },
  { lang: "SQL", files: 63 },
];

const STAGES = [
  { stage: "解析", value: 34 },
  { stage: "摘要", value: 28 },
  { stage: "向量化", value: 21 },
  { stage: "图谱", value: 17 },
];

/**
 * 等容器宽度就绪再渲染图表。
 *
 * heitu 的 charts 在挂载那一刻读 `containerRef.clientWidth` 定 canvas 宽度，
 * 且 effect 依赖为空——本组件是 dynamic 动态导入的，首次挂载时宽度还是 0，
 * 图表就永久空白（组件库内部没有 ResizeObserver 兜底）。
 * 这里量到真实宽度后再挂载，并把宽度作为 key，窗口缩放也能跟着重建。
 */
function useReadyWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const sync = () => setWidth(Math.round(el.getBoundingClientRect().width));
    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

export default function ChartsDemo() {
  const [kind, setKind] = useState<Kind>("line");
  const { ref: boxRef, width } = useReadyWidth();
  const [picked, setPicked] = useState<string>("");

  const common = useMemo(
    () => ({
      height: 280,
      colors: PALETTE,
      // 关掉入场动画：heitu 的揭幕遮罩（Rect fillStyle '#0F172A'）在动画收尾时
      // done 回调没能把它清零，会永久留一条黑边压在图表上——作品集里这是硬伤。
      // 组件库修好后可以打开。
      animation: false as const,
      style: { width: "100%" },
    }),
    []
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented
          value={kind}
          onChange={(v) => {
            setKind(v as Kind);
            setPicked("");
          }}
          options={[
            { label: "折线图", value: "line" },
            { label: "柱状图", value: "bar" },
            { label: "饼图", value: "pie" },
          ]}
        />
        <span className="text-[10px] tracking-wide text-faint">
          点击图元查看数据 · canvas 渲染
        </span>
      </div>

      <div ref={boxRef} className="border border-line bg-panel p-3">
        {width === 0 && (
          <div className="flex h-[280px] items-center justify-center text-[11px] text-faint">
            测量画布尺寸…
          </div>
        )}
        {width > 0 && kind === "line" && (
          <LineChartComponent
            key={`line-${width}`}
            width={width}
            {...common}
            data={TREND}
            xField="month"
            yField={["indexed", "chats"]}
            smooth
            onClickItem={(item) => setPicked(JSON.stringify(item))}
          />
        )}
        {width > 0 && kind === "bar" && (
          <BarChartComponent
            key={`bar-${width}`}
            width={width}
            {...common}
            data={LANGS}
            xField="lang"
            yField="files"
            onClickItem={(item) => setPicked(JSON.stringify(item))}
          />
        )}
        {width > 0 && kind === "pie" && (
          <PieChartComponent
            key={`pie-${width}`}
            width={width}
            {...common}
            data={STAGES}
            angleField="value"
            colorField="stage"
            onClickItem={(item) => setPicked(JSON.stringify(item))}
          />
        )}
      </div>

      <div className="border border-line bg-shade px-3 py-2 text-[11px] leading-relaxed text-ink2">
        {picked ? `选中：${picked}` : "尚未选中任何图元"}
      </div>
    </div>
  );
}
