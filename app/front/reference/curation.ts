import type { CurationTab, OverrideMap, SignatureMap } from "./types";

/**
 * 策展清单 + 说明覆盖层（M15）——**这个文件由人手写，脚本永不写入它**。
 *
 * 与 `generated.ts` 分成两个文件是硬约束：合并的话，人补完覆盖条目、下次跑
 * `npm run gen:reference` 就被冲掉了。
 *
 * ## 只能写 type-only import
 *
 * `scripts/gen-heitu-reference.mjs` 读取本文件的方式是 `ts.transpileModule` 转译后
 * 经 `data:` URL 动态 import（Node 20 不支持直接 import .ts，而 `.mjs` 又拿不到类型检查）。
 * 转译产物必须自包含，因此这里**只能出现 `import type`**——`isolatedModules: true`
 * 保证它被完整擦除。一旦写了值导入（哪怕是个常量），转译后的相对路径解析不了，脚本会崩。
 *
 * ## 人写的内容优先，机器提取兜底
 *
 * 说明的取值优先级是「本文件的 OVERRIDES → 源 `.d.ts` 的 TSDoc」，签名同理
 * （SIGNATURES → 脚本提取）。这个方向是有理由的：机器提取保证的是「不遗漏、不腐烂」，
 * 不是「最适合展示」。源 TSDoc 常在讲实现约束（如「不在顶层条件 return」），
 * 而橱窗读者要知道的是这东西干什么、什么时候用。
 *
 * 所以这里不是「填空」而是「择优」——只在人写得更好时才写，写了就以人写的为准。
 * FormRender 的 TSDoc 覆盖率 97% 且质量够用，一条没写；canvas 覆盖率 6%，40 条全靠人写。
 * 脚本对「两处都有」的条目只作中性告知，不催促删除。
 */

/**
 * 各 tab 展示哪些接口的哪些字段。数组顺序即页面顺序。
 *
 * 四个 tab 已齐（3.1 FormRender · 5.1 Charts · 6.1 Canvas · 7.2 Hooks）。
 */
export const CURATION: CurationTab[] = [
  {
    tab: "form",
    groups: [
      {
        title: "FormRender Props",
        interfaceName: "IFormRenderProps",
        fields: ["config", "form", "gutter"],
        inheritedFrom: "其余继承 antd `FormProps`（demo 里的 `layout`、`initialValues` 即来自那边）",
        note: "自有字段还有 isSub（嵌套子表单）与 extra（额外内容），FormRenderDemo 没演示，故不在表内。",
      },
      {
        title: "表单项配置",
        interfaceName: "IItem",
        fields: ["type", "name", "label", "rules", "nodeProps", "watch", "watchClean", "span"],
        note: "config 数组里的一项。写成二维数组即一行多项，span 分配栅格；另有 divider 项走 IDividerItem。",
      },
      {
        title: "控件 props",
        interfaceName: "INodeProps",
        fields: ["service"],
        note: "此外还有索引签名 [key: string]: unknown——demo 里的 placeholder、options、min、rows 都由它兜住，原样透传给底层 antd 控件。",
      },
    ],
  },
  {
    tab: "charts",
    groups: [
      {
        title: "图表通用配置",
        interfaceName: "IChartConfig",
        fields: ["width", "height", "data", "animation", "colors", "onClickItem"],
        note: "四种图表共用，全站只列这一次。React 组件版不必传 container（组件内部自建），另外还接受 style 与 className——那两个加在 IChartProps 上，不属于本接口。公共配置里的 tooltip、legend、padding demo 未演示，故不在表内。",
      },
      {
        title: "折线图 LineChart",
        interfaceName: "ILineChartConfig",
        fields: ["xField", "yField", "smooth"],
        inheritedFrom: "其余继承「图表通用配置」（IChartConfig）",
        note: "自有字段还有 point（数据点大小，false 不显示），demo 未演示。",
      },
      {
        title: "柱状图 BarChart",
        interfaceName: "IBarChartConfig",
        fields: ["xField", "yField"],
        inheritedFrom: "其余继承「图表通用配置」（IChartConfig）",
        note: "自有字段还有 barWidth、group（分组）、stack（堆叠）、radius（柱子圆角）、colorField（颜色映射字段），demo 未演示。",
      },
      {
        title: "饼图 PieChart",
        interfaceName: "IPieChartConfig",
        fields: ["angleField", "colorField"],
        inheritedFrom: "其余继承「图表通用配置」（IChartConfig）",
        note: "自有字段还有 innerRadius（大于 0 即环形图）与 label（标签位置），demo 未演示。",
      },
      {
        title: "双轴柱线图 BarLineChart",
        interfaceName: "IBarLineChartConfig",
        fields: [
          "xField",
          "yFieldBar",
          "yFieldLine",
          "barColor",
          "lineColor",
          "yLabelLeft",
          "yLabelRight",
          "smooth",
        ],
        inheritedFrom: "其余继承「图表通用配置」（IChartConfig）",
        note: "自有字段还有 barWidth、radius、point，demo 未演示。",
      },
    ],
  },
  {
    tab: "canvas",
    groups: [
      {
        title: "Stage 画布配置",
        interfaceName: "IOption",
        fields: ["container", "width", "height", "backgroundColor"],
        note: "`stage.buildContentDOM(config)` 的入参。Stage 会接管 container 的 id、className 与内联宽高。",
      },
      {
        title: "Rect 矩形",
        interfaceName: "IRect",
        fields: ["x", "y", "width", "height", "fillStyle", "strokeStyle", "lineWidth"],
      },
      {
        title: "Circle 圆 / 圆环",
        interfaceName: "ICircle",
        fields: ["x", "y", "radius", "fillStyle", "strokeStyle", "border", "index"],
      },
      {
        title: "Line 线段",
        interfaceName: "ILine",
        fields: ["start", "end", "strokeStyle", "lineWidth", "lineCap"],
      },
      {
        title: "Text 文本",
        interfaceName: "IText",
        fields: ["x", "y", "content", "fillStyle", "fontSize", "fontFamily"],
      },
      {
        title: "Custom 自定义路径",
        interfaceName: "ICustom",
        fields: ["x", "y", "path2D", "fillStyle", "strokeStyle", "lineWidth"],
      },
      {
        title: "Group 分组",
        interfaceName: "Group",
        fields: ["draggable"],
        note: "取自 Group 类而非配置接口——它的构造参数是内联的 `{ draggable: boolean }`，没有具名接口可点。Rect、Circle 等图元也能拖，但走的是运行时鸭子类型（给实例赋 `draggable`），类声明里没有这个属性，故不在表内。",
      },
      {
        title: "Animate 补间动画配置",
        interfaceName: "AnimateCartoonConfig",
        fields: ["duration", "easing", "during", "done"],
        note: "`new Animate(startProp, targetProp, cfg)` 的第三个参数。startProp 与 targetProp 是同名属性的起止值，逐帧插值后由 during 写回图元。",
      },
    ],
  },
  {
    tab: "hooks",
    groups: [
      {
        kind: "functions",
        title: "数据请求",
        from: "hooks",
        fields: ["useAsyncFn", "useCancelAsyncFn", "usePolling", "useHtAxios"],
        note: "异步状态机、可取消请求、轮询与 axios 实例。",
      },
      {
        kind: "functions",
        title: "DOM 观察",
        from: "hooks",
        fields: ["useElementSize", "useResizeObserver", "useInView", "useDevicePixelRatio"],
        note: "尺寸、可见性与设备像素比，SSR 安全。",
      },
      {
        kind: "functions",
        title: "存储",
        from: "hooks",
        fields: ["useLocalStorage", "useSessionStorage", "useCookie"],
        note: "三种持久化介质，同一套读写签名。",
      },
      {
        kind: "functions",
        title: "交互",
        from: "hooks",
        fields: ["useCountDown", "useInfiniteScroll", "useWebSocket", "useImageLoad"],
        note: "倒计时、无限滚动、长连接与图片预载。",
      },
      {
        kind: "functions",
        title: "工具",
        from: "hooks",
        fields: ["usePrevious", "useWindowSize", "useDeepCompareEffect", "createContainer"],
        note: "上一次的值、深比较依赖、窗口尺寸与状态容器。",
      },
    ],
  },
];

/**
 * 为源里没有 TSDoc 的字段补中文说明。键必须是 `接口名.字段名`。
 *
 * **错误的说明比空白更有害**：空白会被脚本拦下，错的说明会原样上线。
 * 不确定的取值（如 `ICircle.border` 的 `0 | 1 | 2` 分别指什么）必须查证
 * `../heitu-platform/packages/heitu/src` 源码或实测确认后再写。
 *
 * canvas 的 40 条均查证自 heitu 1.1.1 源码（构造函数默认值 + draw 实现），
 * 与 `node_modules/heitu/dist` 的编译产物逐条核对过。
 *
 * 一条贯穿全部图元的构造器行为，各字段说明里不再重复：配置对象经
 * `forIn(config, (value, key) => { if (value) ... })` 赋值，falsy 值
 * （`0`、`''`、`false`、`null`）会被静默忽略，落回默认值。
 *
 * charts 的 10 条同样查证自源码（`BaseChart` 的回落链、`core/animate.ts` 的
 * 默认 duration / easing、`onClickItem` 的实参），只补 `.d.ts` 里没有 TSDoc 的字段。
 *
 * ## hooks 走 FunctionGroup，键前缀是 `from` 的值
 *
 * hooks 不是「一个接口的若干字段」，所以用 `kind: "functions"` + `from: "hooks"`，
 * 键形如 `hooks.useAsyncFn`。实测 19 个导出有三种声明形态，脚本取签名时都要认：
 * `declare function`（5 个，如 useAsyncFn）、`declare const X: 类型引用`
 * （3 个，如 useWindowSize）、`declare const X: 内联函数类型`（11 个，如 useCountDown）。
 *
 * 各 hook 的 options 入参接口一律不展开（fb 定）——橱窗在这一节承诺的是
 * 「有哪些 hook、怎么调用」，不是每个可选参数的详解。
 *
 * hooks 的 desc 迁自 `app/front/demos/hooks-reference.ts`（D7：保住人工润色过的
 * 中文），但不是整批照搬：有 6 条的 `.d.ts` 已有 TSDoc，逐条取优后保留 4 条、
 * 让另 2 条改用源 TSDoc——判据与逐条理由见该批条目上方的注释。
 */
export const OVERRIDES: OverrideMap = {
  // ── Stage ──
  "IOption.container":
    "挂载画布的宿主元素。必须是真实 HTMLElement，否则 buildContentDOM 直接抛错；Stage 会改写它的 id、className 与内联宽高。",
  "IOption.width":
    "画布宽度（px）。不传则宿主元素按 100% 铺满父级——但位图尺寸取的是当时的 offsetWidth，父级宽度为 0 时画出来是空白。",
  "IOption.height": "画布高度（px），不传为 500。",
  "IOption.backgroundColor":
    "画布背景色，直接写到 canvas 的 style.background；不传则保持透明。",

  // ── Rect ──
  "IRect.x": "矩形左上角横坐标，默认 100。",
  "IRect.y": "矩形左上角纵坐标，默认 100。",
  "IRect.width": "矩形宽度，默认 100。",
  "IRect.height": "矩形高度，默认 100。",
  "IRect.fillStyle": "填充色。默认 null，即不填充。",
  "IRect.strokeStyle": "描边色。默认 null，此时沿用画布上下文当前的描边色。",
  "IRect.lineWidth":
    "描边宽度，默认 null。描边与否只看这个字段——不设就完全不描边，光设 strokeStyle 画不出边框。",

  // ── Circle ──
  "ICircle.x": "圆心横坐标，默认 10。",
  "ICircle.y": "圆心纵坐标，默认 10。",
  "ICircle.radius": "半径，默认 8。",
  "ICircle.fillStyle": "填充色，默认空串，即不填充。",
  "ICircle.strokeStyle": "描边色，默认空串，此时沿用画布上下文当前的描边色。",
  "ICircle.border":
    "绘制模式，默认 0。1 只描边不填充；0 与 2 在当前实现下完全相同，都是先 stroke 再 fill——源码把 0 注释为「填充」，但那一分支同样执行了描边，所以写 0 也会描出 lineWidth 宽的边。要真正只填充，得把 lineWidth 或 strokeStyle 留空。",
  "ICircle.index":
    "绘制层级，数值小的先画、位于下层。传 0 等同不传：add 时 falsy 的 index 会被替换为当前子节点数量，也就是加入顺序。",

  // ── Line ──
  "ILine.start": "起点坐标，默认 { x: 10, y: 10 }。",
  "ILine.end":
    "终点坐标，默认 { x: 100, y: 100 }。路径按 start → points → end 依次连接，points 为空时就是一条直线。",
  "ILine.strokeStyle": "线条颜色，默认 'black'。",
  "ILine.lineWidth": "线宽，默认 1。",
  "ILine.lineCap":
    "线段端点样式，同 canvas 的 lineCap：butt 平头（默认）、round 圆头、square 方头。",

  // ── Text ──
  "IText.x": "文本锚点横坐标，默认 100。",
  "IText.y":
    "文本锚点纵坐标，默认 100。配合默认的 textBaseline（top）与 textAlign（left），锚点即文字左上角。",
  "IText.content": "文本内容。必填——构造时为空会抛 Text must has content。",
  "IText.fillStyle": "文字颜色，默认 '#333'。",
  "IText.fontSize": "字号（px），默认 14。",
  "IText.fontFamily": "字体族，默认 '微软雅黑'。",

  // ── Custom ──
  "ICustom.x":
    "声明里有，但 draw 不读它——图形位置完全由 path2D 内的坐标决定，改这个字段不会平移图形。",
  "ICustom.y":
    "声明里有，但 draw 不读它——图形位置完全由 path2D 内的坐标决定，改这个字段不会平移图形。",
  "ICustom.path2D":
    "图形路径，必填，为空会在构造时抛错。命中检测也走这条路径，凹形状同样判定准确。",
  "ICustom.fillStyle": "填充色。默认 null，即不填充。",
  "ICustom.strokeStyle": "描边色，默认 null，此时沿用画布上下文当前的描边色。",
  "ICustom.lineWidth": "描边宽度，默认 1——与 Rect 不同，Custom 默认就会描边。",

  // ── Group ──
  "Group.draggable":
    "整组是否可拖拽，子节点共享一次命中与拖拽、坐标相对父节点。传 false 与不传等效：构造器只赋值 truthy 的配置项，两种写法都得到不可拖的分组。",

  // ── Animate ──
  "AnimateCartoonConfig.duration": "单次动画时长（ms），默认 1000。",
  "AnimateCartoonConfig.easing":
    "缓动函数名，默认 'linear'。取值须是 easingFuncs 的键：linear，以及 quadratic、cubic、quartic、quintic、sinusoidal、exponential、circular、elastic、back、bounce 各自的 In / Out / InOut，共 31 个。类型标注是 any，名字写错在第一帧就会报错。",
  "AnimateCartoonConfig.during":
    "每帧回调 (percent, newState)。percent 是缓动之后的进度而非线性时间比；newState 是本帧插值出的属性对象，取值写回图元后需自行重绘。",
  "AnimateCartoonConfig.done":
    "动画正常跑完时触发一次。iterationCount 为 Infinity 时永不触发；1.1.0 只有类型声明，1.1.1 起才真正实现。",

  // ── 图表通用配置（IChartConfig）──
  "IChartConfig.width":
    "画布宽度（px）。不传则取容器的 clientWidth，仍拿不到时回落 400。",
  "IChartConfig.height":
    "画布高度（px）。不传则取容器的 clientHeight，仍拿不到时回落 300。",
  "IChartConfig.data":
    "数据源数组，每项是一条记录。xField、yField、angleField 等配置填的都是这些记录里的键名。",
  "IChartConfig.animation":
    "入场动画。不传或传 false 直接绘出终态；传 true 用默认值，传 { duration, easing } 可调——duration 默认 600ms，easing 默认 'cubicOut'，取值同 canvas 的 Animate。",
  "IChartConfig.colors":
    "调色板，按系列顺序取用。不传则用内置的 8 色 DEFAULT_COLORS。",
  "IChartConfig.onClickItem":
    "点击图元的回调，收到 (item, index)。item 是 data 里那条原始记录本身，不是内部图元对象——所以可以直接读你自己的字段。",

  // ── 四种图表的自有字段（只补没有 TSDoc 的）──
  "ILineChartConfig.xField":
    "X 轴字段名，取 data 每项中该键的值作为分类轴刻度。",
  "IBarChartConfig.xField":
    "X 轴字段名，取 data 每项中该键的值作为分类轴刻度。",
  "IBarChartConfig.yField":
    "Y 轴字段名，该键的值决定柱子高度。与折线图不同，这里只接受单个字段，不支持数组。",
  "IBarLineChartConfig.xField":
    "X 轴字段名，柱与线共用同一条分类轴。",

  // ── hooks（迁自 hooks-reference.ts 的人工 desc）──
  //
  // 原计划整批迁入（D7「一句不丢」），实测发现 19 个里有 6 个 .d.ts 也有 TSDoc。
  // 逐条比对后按**面向使用者的说明优于面向实现者的说明**取优——赢的那份留下，
  // 输的那份不写（现在是人写优先，写在这里的就是页面上显示的）：
  //
  //   保留人工版（4 条，标 ※）——源 TSDoc 讲的是实现，不是用途：
  //     useInfiniteScroll   源里几乎没写；人工版给出「自带 loading 与到底判断」
  //     useLocalStorage     源里在讲 Rules of Hooks；人工版给出「可自定义序列化器」
  //     useSessionStorage   源里讲写入时机；人工版点出「作用域限于当前标签页」这一关键差异
  //     useDevicePixelRatio 源里讲 matchMedia 监听；人工版给出「canvas 高清必备」的使用场景
  //
  //   改用源 TSDoc（2 条，已从本表删除）——源写得更准，人工版有遗漏：
  //     usePrevious    源里写明「首次渲染返回 undefined」，人工版漏了
  //     useWindowSize  源里写明 SSR 下返回 { width: 0, height: 0 }，人工版只说「SSR 安全」
  //
  // 那 4 条源里也有 TSDoc，脚本会中性告知「两处都有」——它们是评估后择优的结果，不是遗漏。
  // 另：本表任何一条都不得写成「同上」——橱窗的表可能重排或筛选，依赖相邻行的表述会失效。
  "hooks.useAsyncFn":
    "把异步函数包成 { loading, value, error } 状态机，手动触发。",
  "hooks.useCancelAsyncFn":
    "同 useAsyncFn，但回调收到取消上下文；组件卸载或重复调用时中断前一次请求。",
  "hooks.usePolling":
    "按间隔轮询一个异步服务，支持成功/失败回调与手动起停。",
  "hooks.useHtAxios":
    "带拦截器的 axios 实例，统一注入请求头与错误处理。",
  "hooks.useElementSize": "订阅元素尺寸，内部走 ResizeObserver。",
  "hooks.useResizeObserver":
    "更底层的 ResizeObserver 封装，自己拿 entry 做事。",
  "hooks.useInView":
    "元素进入视口时置 true，可只触发一次（懒加载常用）。",
  // ※ 有 TSDoc
  "hooks.useDevicePixelRatio":
    "SSR 初值为 1，挂载后同步真实 DPR 并监听变化（canvas 高清必备）。",
  // ※ 有 TSDoc
  "hooks.useLocalStorage": "localStorage 持久化，可自定义序列化器。",
  // ※ 有 TSDoc
  "hooks.useSessionStorage":
    "sessionStorage 持久化，用法同 useLocalStorage，但作用域限于当前标签页。",
  "hooks.useCookie": "基于 js-cookie，可带 expires / path 等属性。",
  "hooks.useCountDown": "秒级倒计时，验证码按钮那类场景。",
  // ※ 有 TSDoc
  "hooks.useInfiniteScroll": "分页累积加载，自带 loading 与到底判断。",
  "hooks.useWebSocket":
    "WebSocket 连接与消息收发，带 open/close/error 回调。",
  "hooks.useImageLoad": "批量预载图片，全部就绪后再渲染，避免闪烁。",
  "hooks.useDeepCompareEffect":
    "依赖做深比较而非引用比较，省去手动 memo 对象依赖。",
  "hooks.createContainer":
    "把任意 hook 提升为 Context 容器，跨组件共享状态。",
};

/**
 * 函数签名覆盖层：键同 `OVERRIDES`，形如 `hooks.useAsyncFn`，仅用于 functions 形态。
 *
 * 优先级同说明——写在这里的以人写的为准，没写的由脚本从 `.d.ts` 提取兜底。
 * 19 个 hook 逐条量过提取长度、并实测过兜底产物后，只有 10 条需要人写，其余 9 条机器版够用：
 *
 *   A. 机器版过长，摊开每个可选参数会把三列表格撑垮（提取长度 → 人工版）：
 *      useHtAxios 816→79 · createContainer 447→76 · useWebSocket 237→100
 *      usePolling 200→79 · useCookie 194→55 · useAsyncFn 156→61
 *      useInfiniteScroll 146→107 · useCancelAsyncFn 139→81
 *
 *   B. 解引用后仍看不清，或带噪音（2 条）——这类是 `declare const X: 类型别名` 形态。
 *      脚本会跨文件解引用再展开，多数情况够用，但两处例外：
 *      useDevicePixelRatio 解引用只走一层，落到 `=> UseDevicePixelRatioReturn` 就停了，
 *      读者看不到里面的 `pixelRatio`；useWindowSize 展开后带 `readonly` 噪音。
 *      同形态的 useDeepCompareEffect 不在此列——它兜底出来是
 *      `(effect: EffectCallback, deps: DependencyList) => void`，比人写的还清楚，故不写。
 *
 * 全部逐条对着 `.d.ts` 的返回值核对过，不是照抄 `hooks-reference.ts`——旧手写版的
 * `createContainer` 写的是 `withProvider`，而 1.1.1 的实际导出是 `withContainer`，
 * 还漏了 `Context`。那正是这次要根治的腐烂。
 */
export const SIGNATURES: SignatureMap = {
  // ── A. 机器版过长 ──
  "hooks.useHtAxios":
    "useHtAxios({ config, requestInterceptorsCallback, ... }) => { get, post, del, put }",
  "hooks.createContainer":
    "createContainer(useHook) => { Provider, useContainer, withContainer, Context }",
  "hooks.useWebSocket":
    "useWebSocket(url, options?) => { readyState, sendMessage, connect, disconnect, latestMessage }",
  "hooks.usePolling":
    "usePolling<T>(service, options?) => { data, loading, error, start, stop, state }",
  "hooks.useCookie": "useCookie(key, options?, defaultValue?) => [value, set]",
  "hooks.useAsyncFn":
    "useAsyncFn<T>(fn, deps?, initialState?) => [AsyncState<T>, T]",
  "hooks.useInfiniteScroll":
    "useInfiniteScroll<T>({ dataSource, fetchData, pageSize, ... }) => { data, loading, hasMore, loadMore, reset }",
  "hooks.useCancelAsyncFn":
    "useCancelAsyncFn<T>(fn: (ctx: CancelContext) => Promise<T>, deps) => AsyncFnReturn",

  // ── B. 机器版是未展开的类型引用 ──
  "hooks.useWindowSize": "useWindowSize() => { width, height }",
  "hooks.useDevicePixelRatio": "useDevicePixelRatio() => { pixelRatio }",
};
