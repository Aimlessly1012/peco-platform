"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Space } from "antd";
import { Animate, Circle, Custom, Group, Line, Rect, Stage, Text } from "heitu";
import FieldTables from "../reference/FieldTables";

/**
 * canvas 引擎 demo：Stage + 六种图元 + 命中检测 + 补间动画。
 *
 * 三节内容由 /front 侧栏切换，每节只画该节要讲的东西——原来一个 Stage 塞三种能力，
 * 图元、拖拽、动画混在一起反而看不清各自是什么。
 *
 * 三个已知坑，都在这里绕开了：
 * 1. Stage 在 buildContentDOM 时读容器尺寸定 canvas 大小，宽度为 0 就画不出东西——
 *    所以沿用 ChartsDemo 的做法，等容器宽度就绪再挂载。
 * 2. Animate 的 done/aborted 自 1.1.1 起才真正触发（1.1.0 只有类型声明），
 *    本页收尾动作挂在 done 上——升级前的写法是 during 里判 percent。
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

const MONO = '"IBM Plex Mono", monospace';
const HEIGHT = 320;

type Section = "shapes" | "hit" | "animate";

/** 等容器宽度就绪：组件库内部不带 ResizeObserver 兜底，宽度 0 时会画出空白。 */
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

/**
 * 文本图元快捷构造。
 * 返回值断言成 never：Stage.add 要的 ChildType 带 remove/destroy/dragging 等字段，
 * 而各图元类的 .d.ts 都没声明它们（同 draggable 的类型缺口），逐个调用点断言太啰嗦。
 */
const label = (x: number, y: number, content: string, color: string = C.muted) =>
  new Text({ x, y, content, fillStyle: color, fontSize: 11, fontFamily: MONO }) as never;

/** 每节的初始提示。做成常量而不是在 effect 里 setState，省掉一次级联渲染。 */
const INITIAL_INFO: Record<Section, string> = {
  shapes: "这一节是静态展示，切到「命中检测」可以点和拖。",
  hit: "点一下图元，或者把方块拖走。",
  animate: "点「播放动画」看小球在两端之间补间往返。",
};

const HINTS: Record<Section, string> = {
  shapes:
    "Stage 是根容器，图元按加入顺序分层绘制。六种内置图元都直接吃 canvas 的绘制参数（fillStyle / strokeStyle / lineWidth）。",
  hit: "点击与拖拽都走同一套碰撞检测：Rect 按矩形、Circle 按半径、Custom 按 Path2D，Group 则把子节点当作一个整体。",
  animate:
    "Animate 在 startProp 与 targetProp 之间按 easing 补间，每帧回调 during 更新图元属性后重绘。",
};

export default function CanvasDemo({ section }: { section: string }) {
  const key = (["shapes", "hit", "animate"].includes(section) ? section : "shapes") as Section;
  const { ref: boxRef, width } = useReadyWidth();
  const hostRef = useRef<HTMLDivElement>(null);
  const pulseRef = useRef<(() => void) | null>(null);
  const resetRef = useRef<(() => void) | null>(null);
  // 交互产生的信息连同它属于哪一节一起存：换节自然回落到初始提示
  const [info, setInfo] = useState<{ section: Section; text: string } | null>(null);
  const infoText = info?.section === key ? info.text : INITIAL_INFO[key];
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

    // ── 背景网格：Line 图元，纯装饰不参与命中 ──
    for (let x = 40; x < width; x += 40) {
      stage.add(
        new Line({
          start: { x, y: 24 },
          end: { x, y: HEIGHT - 24 },
          strokeStyle: C.hair,
          lineWidth: 1,
        }) as never
      );
    }

    if (key === "shapes") {
      // 六种图元各来一个，标注名字
      stage.add(
        new Rect({
          x: 40, y: 70, width: 104, height: 64,
          fillStyle: C.shade, strokeStyle: C.accent, lineWidth: 2,
        }) as never,
        label(40, 154, "Rect")
      );
      stage.add(
        new Circle({
          x: 232, y: 102, radius: 34,
          fillStyle: C.accent, strokeStyle: C.accent, border: 0, index: 0,
        }) as never,
        label(198, 154, "Circle")
      );
      stage.add(
        new Line({
          start: { x: 300, y: 134 }, end: { x: 392, y: 70 },
          strokeStyle: C.ink2, lineWidth: 2, lineCap: "round",
        }) as never,
        label(300, 154, "Line")
      );

      const group = new Group({ draggable: false });
      group.add(
        new Rect({
          x: 430, y: 74, width: 112, height: 56,
          fillStyle: C.paper, strokeStyle: C.line, lineWidth: 1,
        }) as never,
        label(446, 108, "Text in Group", C.ink2)
      );
      stage.add(group as never, label(430, 154, "Group + Text"));

      const path = new Path2D();
      path.moveTo(600, 132);
      path.lineTo(636, 70);
      path.lineTo(672, 132);
      path.closePath();
      stage.add(
        new Custom({ x: 0, y: 0, path2D: path, fillStyle: C.danger, strokeStyle: C.danger, lineWidth: 1 }) as never,
        label(600, 154, "Custom (Path2D)")
      );

      stage.add(label(24, 40, "六种图元 · 按加入顺序分层绘制", C.muted));
    }

    if (key === "hit") {
      const say = (text: string) => setInfo({ section: "hit", text });

      const rect = new Rect({
        x: 56, y: 74, width: 112, height: 68,
        fillStyle: C.shade, strokeStyle: C.accent, lineWidth: 2,
      });
      makeDraggable(rect);
      rect.on("click", () => say("Rect · 命中按矩形包围盒判定 · 可拖拽"));
      stage.add(rect as never);

      const circle = new Circle({
        x: 268, y: 108, radius: 38,
        fillStyle: C.accent, strokeStyle: C.accent, border: 0, index: 0,
      });
      makeDraggable(circle);
      circle.on("click", () => say("Circle · 命中按半径算，角落不算命中 · 可拖拽"));
      stage.add(circle as never);

      const group = new Group({ draggable: true });
      group.add(
        new Rect({
          x: 380, y: 78, width: 132, height: 60,
          fillStyle: C.paper, strokeStyle: C.line, lineWidth: 1,
        }) as never,
        label(396, 114, "整组拖动", C.ink2)
      );
      group.on("click", () => say("Group · 子节点共享一次命中与拖拽，坐标相对父节点"));
      stage.add(group as never);

      const path = new Path2D();
      path.moveTo(576, 138);
      path.lineTo(616, 74);
      path.lineTo(656, 138);
      path.closePath();
      const tri = new Custom({ x: 0, y: 0, path2D: path, fillStyle: C.danger, strokeStyle: C.danger, lineWidth: 1 });
      tri.on("click", () => say("Custom · 命中走 Path2D 本身，凹形状也准"));
      stage.add(tri as never);

      stage.add(label(24, 40, "点击任意图元 · 方块与圆可拖拽"));
    }

    if (key === "animate") {
      const ball = new Circle({
        x: 90, y: 150, radius: 30,
        fillStyle: C.accent, strokeStyle: C.accent, border: 0, index: 0,
      });
      const track = new Line({
        start: { x: 90, y: 200 },
        end: { x: Math.max(width - 90, 260), y: 200 },
        strokeStyle: C.line,
        lineWidth: 1,
      });
      stage.add(track as never, ball as never);
      stage.add(label(24, 40, "Animate · cubicOut 缓动 · 位置与半径同时补间"));

      const farX = Math.max(width - 90, 260);
      pulseRef.current = () => {
        const from = { x: ball.x, radius: ball.radius };
        const to = { x: ball.x > (90 + farX) / 2 ? 90 : farX, radius: 46 };
        const anim = new Animate(from, to, {
          duration: 720,
          easing: "cubicOut",
          during: (_percent, state) => {
            ball.x = Number(state.x);
            ball.radius = Number(state.radius);
            stage.batchDraw(stage);
          },
          // 1.1.1 起 done 真的会触发（1.1.0 只有类型没有实现），收尾不再挤在 during 里
          done: () => {
            ball.radius = 30;
            stage.batchDraw(stage);
            setPlaying(false);
            setInfo({ section: "animate", text: `到位：x = ${Math.round(ball.x)}，半径已归位 30` });
          },
        });
        anim.start();
      };
      resetRef.current = () => {
        ball.x = 90;
        ball.radius = 30;
        stage.batchDraw(stage);
        setInfo({ section: "animate", text: "已复位" });
      };
    }

    stage.batchDraw(stage);

    return () => {
      pulseRef.current = null;
      resetRef.current = null;
      stage.destroy();
      host.innerHTML = "";
    };
  }, [width, key]);

  const play = useCallback(() => {
    if (playing || !pulseRef.current) return;
    setPlaying(true);
    pulseRef.current();
  }, [playing]);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[11px] leading-relaxed text-muted">{HINTS[key]}</p>

      {key === "animate" && (
        <Space>
          <Button type="primary" onClick={play} disabled={playing}>
            {playing ? "播放中…" : "播放动画"}
          </Button>
          <Button onClick={() => resetRef.current?.()}>复位</Button>
        </Space>
      )}

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
        {infoText}
      </div>

      {/* 上面这些图元的构造参数，在这里逐个解释 */}
      <FieldTables tab="canvas" />
    </div>
  );
}
