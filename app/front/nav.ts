/**
 * /front 的两级导航：顶部 tab 是大类，左侧栏是当前 tab 的子项。
 *
 * 单独抽一个文件，是因为 page 与各 demo 都要引用 section 的 key，
 * 放在一处才不会两边写错字符串。
 */

export interface SectionDef {
  key: string;
  label: string;
  /** 侧栏项下方的一行小字，说明这一节讲什么 */
  hint: string;
}

export interface TabDef {
  key: TabKey;
  label: string;
  /** 内容区标题栏那行 LABEL */
  caption: string;
  sections: SectionDef[];
}

export type TabKey = "form" | "charts" | "canvas" | "hooks";

export const TABS: TabDef[] = [
  {
    key: "form",
    label: "FormRender",
    caption: "FORM RENDER · 配置即表单",
    sections: [
      { key: "basic", label: "基础用法", hint: "一维/二维配置、分割线" },
      { key: "linkage", label: "联动演示", hint: "watch 字段 + service 异步选项" },
      { key: "validate", label: "校验与提交", hint: "rules、提交取值、重置" },
    ],
  },
  {
    key: "charts",
    label: "Charts",
    caption: "CHARTS · canvas 自绘",
    sections: [
      { key: "line", label: "折线图", hint: "多字段、平滑曲线" },
      { key: "bar", label: "柱状图", hint: "分类对比" },
      { key: "pie", label: "饼图", hint: "占比构成" },
      { key: "barLine", label: "双轴柱线图", hint: "左右轴不同量纲" },
    ],
  },
  {
    key: "canvas",
    label: "Canvas 引擎",
    caption: "CANVAS ENGINE · 图元 / 命中 / 动画",
    sections: [
      { key: "shapes", label: "图元一览", hint: "六种图元与 Stage 分层" },
      { key: "hit", label: "命中检测", hint: "点击拾取与拖拽" },
      { key: "animate", label: "补间动画", hint: "Animate 缓动" },
    ],
  },
  {
    key: "hooks",
    label: "Hooks",
    caption: "HOOKS · 19 个，按类别归组",
    sections: [
      { key: "async", label: "数据请求", hint: "异步状态机、轮询" },
      { key: "dom", label: "DOM 观察", hint: "尺寸、可见性、DPR" },
      { key: "storage", label: "存储", hint: "local / session / cookie" },
      { key: "interaction", label: "交互", hint: "倒计时、无限滚动" },
      { key: "util", label: "工具", hint: "上一次的值、窗口尺寸" },
      { key: "all", label: "全部 API", hint: "19 个签名速查" },
    ],
  },
];

export const tabByKey = (key: TabKey): TabDef =>
  TABS.find((t) => t.key === key) ?? TABS[0];
