"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Space } from "antd";
import { Animate, Circle, Custom, Group, Line, Rect, Stage, Text } from "heitu";

/**
 * canvas 引擎 demo：Stage + 六种图元 + 命中检测 + 拖拽 + 补间动画。
 *
 * 两个已知坑，都在这里绕开了：
 * 1. Stage 在 buildContentDOM 时读容器尺寸定 canvas 大小，宽度为 0 就画不出东西——
 *    所以沿用 ChartsDemo 的做法，等容器宽度就绪再挂载。
 * 2. Animate 的 cfg.done / cfg.aborted 在实现里从未被调用（类型声明里有，代码里没有），
 *    所以收尾动作不能挂在 done 上，这里改用 during 的 percent 判断。
 * 3. 拖拽在运行时是读 `node.draggable`（鸭子类型），但 Rect/Circle/Line/Text/Custom
 *    这些类的 .d.ts 都没声明该属性——只有 ChildType 接口和 Group 类有，所以要断言。
 */

/** 给图元开启拖拽：绕开上面第 3 条的类型缺口。 */
function makeDraggable(node: object): void {
  (node as { draggable?: boolean }).draggable = true;
}

const C = {
  accent: "#0e7a45",
  ink: "#17171a",
  ink2: "#4a4842",
  muted: "#6f6d66",
  line: "#d9d7cf",
  hair: "#eceae3",
  shade: "#faf9f5",
  danger: "#b8422f",
  paper: "#f5f4ef",
} as const;

const HEIGHT = 320;

/** 等容器宽度就绪（同 ChartsDemo）：组件库内部不带 ResizeObserver 兜底。 */
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

interface StageHandle {
  stage: InstanceType<typeof Stage>;
  pulse: () => void;
  reset: () => void;
}

export default function CanvasDemo() {
  const { ref: boxRef, width } = useReadyWidth();
  const hostRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<StageHandle | null>(null);
  const [picked, setPicked] = useState("拖动方块或圆形试试，点击任意图元查看信息");
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || width === 0) return;

    const stage = new Stage();
    stage.buildContentDOM({
      container: host,
      width,
      height: HEIGHT,
      backgroundColor: "transparent",
    });

    const say = (text: string) => setPicked(text);

    // ── 背景网格：Line 图元，纯装饰不参与命中 ──
    for (let x = 40; x < width; x += 40) {
      stage.add(
        new Line({
          start: { x, y: 20 },
          end: { x, y: HEIGHT - 20 },
          strokeStyle: C.hair,
          lineWidth: 1,
        }) as never
      );
    }

    // ── 可拖拽的矩形 ──
    const rect = new Rect({
      x: 48,
      y: 70,
      width: 108,
      height: 68,
      fillStyle: C.shade,
      strokeStyle: C.accent,
      lineWidth: 2,
    });
    makeDraggable(rect);
    rect.on("click", () => say("Rect · 可拖拽 · fillStyle=shade / strokeStyle=accent"));
    stage.add(rect as never);

    // ── 可拖拽的圆 ──
    const circle = new Circle({
      x: 250,
      y: 104,
      radius: 38,
      fillStyle: C.accent,
      strokeStyle: C.accent,
      border: 0,
      index: 0,
    });
    makeDraggable(circle);
    circle.on("click", () => say("Circle · 可拖拽 · 命中检测按半径算，不是包围盒"));
    stage.add(circle as never);

    // ── Group：两个图元编成一组，一起拖 ──
    const group = new Group({ draggable: true });
    const badge = new Rect({
      x: 360,
      y: 74,
      width: 132,
      height: 60,
      fillStyle: C.paper,
      strokeStyle: C.line,
      lineWidth: 1,
    });
    const badgeText = new Text({
      x: 376,
      y: 110,
      content: "Group 整组拖动",
      fillStyle: C.ink2,
      fontSize: 13,
      fontFamily: '"IBM Plex Mono", monospace',
    });
    group.add(badge as never, badgeText as never);
    group.on("click", () => say("Group · 子节点共享一次拖拽与命中，坐标相对父节点"));
    stage.add(group as never);

    // ── Custom：Path2D 自定义形状（这里画一个三角） ──
    const path = new Path2D();
    path.moveTo(560, 138);
    path.lineTo(600, 70);
    path.lineTo(640, 138);
    path.closePath();
    const tri = new Custom({
      x: 0,
      y: 0,
      path2D: path,
      fillStyle: C.danger,
      strokeStyle: C.danger,
      lineWidth: 1,
    });
    tri.on("click", () => say("Custom · 直接吃 Path2D，任意形状都能进命中检测"));
    stage.add(tri as never);

    // ── 说明文字 ──
    stage.add(
      new Text({
        x: 24,
        y: 34,
        content: "Stage · Rect · Circle · Line · Text · Group · Custom",
        fillStyle: C.muted,
        fontSize: 11,
        fontFamily: '"IBM Plex Mono", monospace',
      }) as never
    );

    const runner = new Text({
      x: 24,
      y: HEIGHT - 26,
      content: "▶ 点上方按钮看 Animate 补间",
      fillStyle: C.muted,
      fontSize: 11,
      fontFamily: '"IBM Plex Mono", monospace',
    });
    stage.add(runner as never);

    stage.batchDraw(stage);

    /** Animate 补间：圆形横向往返 + 半径呼吸。 */
    const pulse = () => {
      const from = { x: circle.x, radius: circle.radius };
      const to = { x: circle.x > width / 2 ? 250 : Math.max(width - 90, 320), radius: 52 };
      const anim = new Animate(from, to, {
        duration: 720,
        easing: "cubicOut",
        during: (percent, state) => {
          circle.x = Number(state.x);
          circle.radius = Number(state.radius);
          stage.batchDraw(stage);
          // done 回调不可用：自己在最后一帧收尾，把半径归位并解锁按钮
          if (percent === 1) {
            circle.radius = 38;
            stage.batchDraw(stage);
            setPlaying(false);
          }
        },
      });
      anim.start();
    };

    const reset = () => {
      rect.x = 48;
      rect.y = 70;
      circle.x = 250;
      circle.y = 104;
      circle.radius = 38;
      stage.batchDraw(stage);
      setPicked("已复位");
    };

    handleRef.current = { stage, pulse, reset };

    return () => {
      handleRef.current = null;
      stage.destroy();
      host.innerHTML = "";
    };
  }, [width]);

  const play = useCallback(() => {
    if (playing) return;
    setPlaying(true);
    handleRef.current?.pulse();
    // Animate 没有 done/aborted 回调，加一道超时兜底，别让按钮永久卡住
    window.setTimeout(() => setPlaying(false), 1200);
  }, [playing]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Space>
          <Button type="primary" onClick={play} disabled={playing}>
            {playing ? "播放中…" : "播放动画"}
          </Button>
          <Button onClick={() => handleRef.current?.reset()}>复位</Button>
        </Space>
        <span className="text-[10px] tracking-wide text-faint">
          图元可拖拽 · 点击命中检测 · 全部由 canvas 自绘
        </span>
      </div>

      <div ref={boxRef} className="border border-line bg-panel p-3">
        {width === 0 && (
          <div
            className="flex items-center justify-center text-[11px] text-faint"
            style={{ height: HEIGHT }}
          >
            测量画布尺寸…
          </div>
        )}
        <div ref={hostRef} style={{ height: width === 0 ? 0 : HEIGHT }} />
      </div>

      <div className="border border-line bg-shade px-3 py-2 text-[11px] leading-relaxed text-ink2">
        {picked}
      </div>
    </div>
  );
}
