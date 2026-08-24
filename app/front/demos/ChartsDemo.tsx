"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  BarChartComponent,
  BarLineChartComponent,
  LineChartComponent,
  PieChartComponent,
} from "heitu";

/**
 * charts demo：canvas 自绘，不依赖重型图表库。
 * 配色传的是终端风令牌，跟站里其他图表口径一致。
 */

const PALETTE = ["#0e7a45", "#4a4842", "#8a8880", "#b8422f", "#d9d7cf"];

/** 由 /front 侧栏传入，取值见 nav.ts 的 charts.sections。 */
type Kind = "line" | "bar" | "pie" | "barLine";

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

/** 双轴：柱子走左轴（绝对量），折线走右轴（比例），量纲差一个数量级也能同框看。 */
const THROUGHPUT = [
  { month: "1月", files: 420, hitRate: 61 },
  { month: "2月", files: 780, hitRate: 68 },
  { month: "3月", files: 640, hitRate: 72 },
  { month: "4月", files: 1180, hitRate: 76 },
  { month: "5月", files: 960, hitRate: 81 },
  { month: "6月", files: 1460, hitRate: 84 },
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

export default function ChartsDemo({ section }: { section: string }) {
  const kind = section as Kind;
  const { ref: boxRef, width } = useReadyWidth();
  // 选中信息连同它属于哪张图一起存：换图表时自然失效，不必用 effect 去清
  const [picked, setPicked] = useState<{ kind: string; text: string } | null>(null);
  const pickedText = picked?.kind === section ? picked.text : "";

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
      <div className="text-[10px] tracking-wide text-faint">
        点击图元查看数据 · canvas 渲染，无 G2/ECharts 依赖
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
            onClickItem={(item) => setPicked({ kind: section, text: JSON.stringify(item) })}
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
            onClickItem={(item) => setPicked({ kind: section, text: JSON.stringify(item) })}
          />
        )}
        {width > 0 && kind === "barLine" && (
          <BarLineChartComponent
            key={`barLine-${width}`}
            width={width}
            {...common}
            data={THROUGHPUT}
            xField="month"
            yFieldBar="files"
            yFieldLine="hitRate"
            barColor={PALETTE[0]}
            lineColor={PALETTE[3]}
            yLabelLeft="索引文件数"
            yLabelRight="命中率 %"
            smooth
            onClickItem={(item) => setPicked({ kind: section, text: JSON.stringify(item) })}
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
            onClickItem={(item) => setPicked({ kind: section, text: JSON.stringify(item) })}
          />
        )}
      </div>

      <div className="border border-line bg-shade px-3 py-2 text-[11px] leading-relaxed text-ink2">
        {pickedText ? `选中：${pickedText}` : "尚未选中任何图元"}
      </div>
    </div>
  );
}
