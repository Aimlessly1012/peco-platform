// ⚠️ 本文件由 scripts/gen-heitu-reference.mjs 生成，**不要手改**。
//
// 要改内容请改 curation.ts（策展清单与说明覆盖层），然后重跑：
//     npm run gen:reference
//
// 升级 heitu 之后同样要重跑——那时没人会去碰 curation.ts，产物却已经对不上新版本了。
// 校验用 npm run check:reference，退出码即结论。
//
// 与 app/fonts.css 同属「脚本生成、产物入库」的既有约定。产物入库不只是为了
// 构建期不依赖脚本——heitu 升级时字段变化会直接出现在 PR 的 diff 里，
// 「新增 smooth」「point 类型变了」一眼可见；构建期生成则完全不可见。
//
// 数据源：node_modules/heitu/dist/**/*.d.ts（不跨仓引用 ../heitu-platform，
// 容器构建时隔壁仓库不存在）。

import type { ReferenceTab } from "./types";

/** 提取自 heitu@1.1.1。版本变了就该重跑，diff 里能看出字段的增删改。 */
export const REFERENCE: ReferenceTab[] = [
  {
    "tab": "form",
    "tables": [
      {
        "title": "FormRender Props",
        "interfaceName": "IFormRenderProps",
        "inheritedFrom": "其余继承 antd `FormProps`（demo 里的 `layout`、`initialValues` 即来自那边）",
        "note": "自有字段还有 isSub（嵌套子表单）与 extra（额外内容），FormRenderDemo 没演示，故不在表内。",
        "rows": [
          {
            "name": "config",
            "type": "(IConfigItem | IConfigItem[])[]",
            "desc": "表单配置：一维数组 = 每行一项，二维数组 = 一行多项，支持分割线",
            "optional": false
          },
          {
            "name": "form",
            "type": "FormInstance",
            "desc": "form 实例",
            "optional": true
          },
          {
            "name": "gutter",
            "type": "[number, number]",
            "desc": "栅格间距",
            "optional": true
          }
        ]
      },
      {
        "title": "表单项配置",
        "interfaceName": "IItem",
        "note": "config 数组里的一项。写成二维数组即一行多项，span 分配栅格；另有 divider 项走 IDividerItem。",
        "rows": [
          {
            "name": "type",
            "type": "React.ComponentType<{ loading?: boolean; disabled?: boolean; }> | string | 'Line'",
            "desc": "控件类型：内置字符串 或 自定义 React 组件",
            "optional": true
          },
          {
            "name": "name",
            "type": "string | Array<string | number>",
            "desc": "字段表单 key",
            "optional": true
          },
          {
            "name": "label",
            "type": "React.ReactNode",
            "desc": "字段名称",
            "optional": true
          },
          {
            "name": "rules",
            "type": "Rule[] | ((form?: FormInstance, watchValue?: IWatchValue) => Rule[])",
            "desc": "表单规则",
            "optional": true
          },
          {
            "name": "nodeProps",
            "type": "INodeProps | ((form?: FormInstance, watchValue?: IWatchValue) => INodeProps)",
            "desc": "控件 props",
            "optional": true
          },
          {
            "name": "watch",
            "type": "string[]",
            "desc": "监听的字段",
            "optional": true
          },
          {
            "name": "watchClean",
            "type": "boolean",
            "desc": "监听字段变更后是否清除当前字段数据（默认 false）",
            "optional": true
          },
          {
            "name": "span",
            "type": "number",
            "desc": "栅格",
            "optional": true
          }
        ]
      },
      {
        "title": "控件 props",
        "interfaceName": "INodeProps",
        "note": "此外还有索引签名 [key: string]: unknown——demo 里的 placeholder、options、min、rows 都由它兜住，原样透传给底层 antd 控件。",
        "rows": [
          {
            "name": "service",
            "type": "(form?: FormInstance, watchValue?: IWatchValue) => Promise<unknown>",
            "desc": "异步数据获取",
            "optional": true
          }
        ]
      }
    ]
  },
  {
    "tab": "charts",
    "tables": [
      {
        "title": "图表通用配置",
        "interfaceName": "IChartConfig",
        "note": "四种图表共用，全站只列这一次。React 组件版不必传 container（组件内部自建），另外还接受 style 与 className——那两个加在 IChartProps 上，不属于本接口。公共配置里的 tooltip、legend、padding demo 未演示，故不在表内。",
        "rows": [
          {
            "name": "width",
            "type": "number",
            "desc": "画布宽度（px）。不传则取容器的 clientWidth，仍拿不到时回落 400。",
            "optional": true
          },
          {
            "name": "height",
            "type": "number",
            "desc": "画布高度（px）。不传则取容器的 clientHeight，仍拿不到时回落 300。",
            "optional": true
          },
          {
            "name": "data",
            "type": "T[]",
            "desc": "数据源数组，每项是一条记录。xField、yField、angleField 等配置填的都是这些记录里的键名。",
            "optional": false
          },
          {
            "name": "animation",
            "type": "boolean | IAnimationConfig",
            "desc": "入场动画。不传或传 false 直接绘出终态；传 true 用默认值，传 { duration, easing } 可调——duration 默认 600ms，easing 默认 'cubicOut'，取值同 canvas 的 Animate。",
            "optional": true
          },
          {
            "name": "colors",
            "type": "string[]",
            "desc": "调色板，按系列顺序取用。不传则用内置的 8 色 DEFAULT_COLORS。",
            "optional": true
          },
          {
            "name": "onClickItem",
            "type": "(item: T, index: number) => void",
            "desc": "点击图元的回调，收到 (item, index)。item 是 data 里那条原始记录本身，不是内部图元对象——所以可以直接读你自己的字段。",
            "optional": true
          }
        ]
      },
      {
        "title": "折线图 LineChart",
        "interfaceName": "ILineChartConfig",
        "inheritedFrom": "其余继承「图表通用配置」（IChartConfig）",
        "note": "自有字段还有 point（数据点大小，false 不显示），demo 未演示。",
        "rows": [
          {
            "name": "xField",
            "type": "string",
            "desc": "X 轴字段名，取 data 每项中该键的值作为分类轴刻度。",
            "optional": false
          },
          {
            "name": "yField",
            "type": "string | string[]",
            "desc": "Y 轴字段，支持多字段绘制多条线",
            "optional": false
          },
          {
            "name": "smooth",
            "type": "boolean",
            "desc": "平滑曲线",
            "optional": true
          }
        ]
      },
      {
        "title": "柱状图 BarChart",
        "interfaceName": "IBarChartConfig",
        "inheritedFrom": "其余继承「图表通用配置」（IChartConfig）",
        "note": "自有字段还有 barWidth、group（分组）、stack（堆叠）、radius（柱子圆角）、colorField（颜色映射字段），demo 未演示。",
        "rows": [
          {
            "name": "xField",
            "type": "string",
            "desc": "X 轴字段名，取 data 每项中该键的值作为分类轴刻度。",
            "optional": false
          },
          {
            "name": "yField",
            "type": "string",
            "desc": "Y 轴字段名，该键的值决定柱子高度。与折线图不同，这里只接受单个字段，不支持数组。",
            "optional": false
          }
        ]
      },
      {
        "title": "饼图 PieChart",
        "interfaceName": "IPieChartConfig",
        "inheritedFrom": "其余继承「图表通用配置」（IChartConfig）",
        "note": "自有字段还有 innerRadius（大于 0 即环形图）与 label（标签位置），demo 未演示。",
        "rows": [
          {
            "name": "angleField",
            "type": "string",
            "desc": "角度映射字段",
            "optional": false
          },
          {
            "name": "colorField",
            "type": "string",
            "desc": "颜色映射字段",
            "optional": false
          }
        ]
      },
      {
        "title": "双轴柱线图 BarLineChart",
        "interfaceName": "IBarLineChartConfig",
        "inheritedFrom": "其余继承「图表通用配置」（IChartConfig）",
        "note": "自有字段还有 barWidth、radius、point，demo 未演示。",
        "rows": [
          {
            "name": "xField",
            "type": "string",
            "desc": "X 轴字段名，柱与线共用同一条分类轴。",
            "optional": false
          },
          {
            "name": "yFieldBar",
            "type": "string | string[]",
            "desc": "柱状图 Y 轴字段（左轴），支持多字段绘制多组柱子",
            "optional": false
          },
          {
            "name": "yFieldLine",
            "type": "string | string[]",
            "desc": "折线图 Y 轴字段（右轴），支持多字段绘制多条线",
            "optional": false
          },
          {
            "name": "barColor",
            "type": "string | string[]",
            "desc": "柱状图颜色，支持多色对应多组柱子",
            "optional": true
          },
          {
            "name": "lineColor",
            "type": "string | string[]",
            "desc": "折线图颜色，支持多色对应多条线",
            "optional": true
          },
          {
            "name": "yLabelLeft",
            "type": "string",
            "desc": "左轴标签",
            "optional": true
          },
          {
            "name": "yLabelRight",
            "type": "string",
            "desc": "右轴标签",
            "optional": true
          },
          {
            "name": "smooth",
            "type": "boolean",
            "desc": "平滑曲线",
            "optional": true
          }
        ]
      }
    ]
  },
  {
    "tab": "canvas",
    "tables": [
      {
        "title": "Stage 画布配置",
        "interfaceName": "IOption",
        "note": "`stage.buildContentDOM(config)` 的入参。Stage 会接管 container 的 id、className 与内联宽高。",
        "rows": [
          {
            "name": "container",
            "type": "HTMLElement",
            "desc": "挂载画布的宿主元素。必须是真实 HTMLElement，否则 buildContentDOM 直接抛错；Stage 会改写它的 id、className 与内联宽高。",
            "optional": false
          },
          {
            "name": "width",
            "type": "number",
            "desc": "画布宽度（px）。不传则宿主元素按 100% 铺满父级——但位图尺寸取的是当时的 offsetWidth，父级宽度为 0 时画出来是空白。",
            "optional": true
          },
          {
            "name": "height",
            "type": "number",
            "desc": "画布高度（px），不传为 500。",
            "optional": true
          },
          {
            "name": "backgroundColor",
            "type": "string",
            "desc": "画布背景色，直接写到 canvas 的 style.background；不传则保持透明。",
            "optional": true
          }
        ]
      },
      {
        "title": "Rect 矩形",
        "interfaceName": "IRect",
        "rows": [
          {
            "name": "x",
            "type": "number",
            "desc": "矩形左上角横坐标，默认 100。",
            "optional": true
          },
          {
            "name": "y",
            "type": "number",
            "desc": "矩形左上角纵坐标，默认 100。",
            "optional": true
          },
          {
            "name": "width",
            "type": "number",
            "desc": "矩形宽度，默认 100。",
            "optional": true
          },
          {
            "name": "height",
            "type": "number",
            "desc": "矩形高度，默认 100。",
            "optional": true
          },
          {
            "name": "fillStyle",
            "type": "string",
            "desc": "填充色。默认 null，即不填充。",
            "optional": true
          },
          {
            "name": "strokeStyle",
            "type": "string",
            "desc": "描边色。默认 null，此时沿用画布上下文当前的描边色。",
            "optional": true
          },
          {
            "name": "lineWidth",
            "type": "number",
            "desc": "描边宽度，默认 null。描边与否只看这个字段——不设就完全不描边，光设 strokeStyle 画不出边框。",
            "optional": true
          }
        ]
      },
      {
        "title": "Circle 圆 / 圆环",
        "interfaceName": "ICircle",
        "rows": [
          {
            "name": "x",
            "type": "number",
            "desc": "圆心横坐标，默认 10。",
            "optional": true
          },
          {
            "name": "y",
            "type": "number",
            "desc": "圆心纵坐标，默认 10。",
            "optional": true
          },
          {
            "name": "radius",
            "type": "number",
            "desc": "半径，默认 8。",
            "optional": true
          },
          {
            "name": "fillStyle",
            "type": "string",
            "desc": "填充色，默认空串，即不填充。",
            "optional": true
          },
          {
            "name": "strokeStyle",
            "type": "string",
            "desc": "描边色，默认空串，此时沿用画布上下文当前的描边色。",
            "optional": true
          },
          {
            "name": "border",
            "type": "0 | 1 | 2",
            "desc": "绘制模式，默认 0。1 只描边不填充；0 与 2 在当前实现下完全相同，都是先 stroke 再 fill——源码把 0 注释为「填充」，但那一分支同样执行了描边，所以写 0 也会描出 lineWidth 宽的边。要真正只填充，得把 lineWidth 或 strokeStyle 留空。",
            "optional": false
          },
          {
            "name": "index",
            "type": "number",
            "desc": "绘制层级，数值小的先画、位于下层。传 0 等同不传：add 时 falsy 的 index 会被替换为当前子节点数量，也就是加入顺序。",
            "optional": false
          }
        ]
      },
      {
        "title": "Line 线段",
        "interfaceName": "ILine",
        "rows": [
          {
            "name": "start",
            "type": "{ x: number; y: number; }",
            "desc": "起点坐标，默认 { x: 10, y: 10 }。",
            "optional": true
          },
          {
            "name": "end",
            "type": "{ x: number; y: number; }",
            "desc": "终点坐标，默认 { x: 100, y: 100 }。路径按 start → points → end 依次连接，points 为空时就是一条直线。",
            "optional": true
          },
          {
            "name": "strokeStyle",
            "type": "string",
            "desc": "线条颜色，默认 'black'。",
            "optional": true
          },
          {
            "name": "lineWidth",
            "type": "number",
            "desc": "线宽，默认 1。",
            "optional": true
          },
          {
            "name": "lineCap",
            "type": "'butt' | 'round' | 'square'",
            "desc": "线段端点样式，同 canvas 的 lineCap：butt 平头（默认）、round 圆头、square 方头。",
            "optional": true
          }
        ]
      },
      {
        "title": "Text 文本",
        "interfaceName": "IText",
        "rows": [
          {
            "name": "x",
            "type": "number",
            "desc": "文本锚点横坐标，默认 100。",
            "optional": true
          },
          {
            "name": "y",
            "type": "number",
            "desc": "文本锚点纵坐标，默认 100。配合默认的 textBaseline（top）与 textAlign（left），锚点即文字左上角。",
            "optional": true
          },
          {
            "name": "content",
            "type": "string",
            "desc": "文本内容。必填——构造时为空会抛 Text must has content。",
            "optional": true
          },
          {
            "name": "fillStyle",
            "type": "string",
            "desc": "文字颜色，默认 '#333'。",
            "optional": true
          },
          {
            "name": "fontSize",
            "type": "number",
            "desc": "字号（px），默认 14。",
            "optional": true
          },
          {
            "name": "fontFamily",
            "type": "string",
            "desc": "字体族，默认 '微软雅黑'。",
            "optional": true
          }
        ]
      },
      {
        "title": "Custom 自定义路径",
        "interfaceName": "ICustom",
        "rows": [
          {
            "name": "x",
            "type": "number",
            "desc": "声明里有，但 draw 不读它——图形位置完全由 path2D 内的坐标决定，改这个字段不会平移图形。",
            "optional": true
          },
          {
            "name": "y",
            "type": "number",
            "desc": "声明里有，但 draw 不读它——图形位置完全由 path2D 内的坐标决定，改这个字段不会平移图形。",
            "optional": true
          },
          {
            "name": "path2D",
            "type": "Path2D | null",
            "desc": "图形路径，必填，为空会在构造时抛错。命中检测也走这条路径，凹形状同样判定准确。",
            "optional": false
          },
          {
            "name": "fillStyle",
            "type": "string",
            "desc": "填充色。默认 null，即不填充。",
            "optional": true
          },
          {
            "name": "strokeStyle",
            "type": "string",
            "desc": "描边色，默认 null，此时沿用画布上下文当前的描边色。",
            "optional": true
          },
          {
            "name": "lineWidth",
            "type": "number",
            "desc": "描边宽度，默认 1——与 Rect 不同，Custom 默认就会描边。",
            "optional": true
          }
        ]
      },
      {
        "title": "Group 分组",
        "interfaceName": "Group",
        "note": "取自 Group 类而非配置接口——它的构造参数是内联的 `{ draggable: boolean }`，没有具名接口可点。Rect、Circle 等图元也能拖，但走的是运行时鸭子类型（给实例赋 `draggable`），类声明里没有这个属性，故不在表内。",
        "rows": [
          {
            "name": "draggable",
            "type": "boolean",
            "desc": "整组是否可拖拽，子节点共享一次命中与拖拽、坐标相对父节点。传 false 与不传等效：构造器只赋值 truthy 的配置项，两种写法都得到不可拖的分组。",
            "optional": false
          }
        ]
      },
      {
        "title": "Animate 补间动画配置",
        "interfaceName": "AnimateCartoonConfig",
        "note": "`new Animate(startProp, targetProp, cfg)` 的第三个参数。startProp 与 targetProp 是同名属性的起止值，逐帧插值后由 during 写回图元。",
        "rows": [
          {
            "name": "duration",
            "type": "number",
            "desc": "单次动画时长（ms），默认 1000。",
            "optional": false
          },
          {
            "name": "easing",
            "type": "any",
            "desc": "缓动函数名，默认 'linear'。取值须是 easingFuncs 的键：linear，以及 quadratic、cubic、quartic、quintic、sinusoidal、exponential、circular、elastic、back、bounce 各自的 In / Out / InOut，共 31 个。类型标注是 any，名字写错在第一帧就会报错。",
            "optional": true
          },
          {
            "name": "during",
            "type": "(percent: number, newState: Record<string, string | number>) => void",
            "desc": "每帧回调 (percent, newState)。percent 是缓动之后的进度而非线性时间比；newState 是本帧插值出的属性对象，取值写回图元后需自行重绘。",
            "optional": true
          },
          {
            "name": "done",
            "type": "() => void",
            "desc": "动画正常跑完时触发一次。iterationCount 为 Infinity 时永不触发；1.1.0 只有类型声明，1.1.1 起才真正实现。",
            "optional": true
          }
        ]
      }
    ]
  },
  {
    "tab": "hooks",
    "tables": [
      {
        "title": "数据请求",
        "interfaceName": "hooks",
        "note": "异步状态机、可取消请求、轮询与 axios 实例。",
        "rows": [
          {
            "name": "useAsyncFn",
            "type": "useAsyncFn<T>(fn, deps?, initialState?) => [AsyncState<T>, T]",
            "desc": "把异步函数包成 { loading, value, error } 状态机，手动触发。",
            "optional": false
          },
          {
            "name": "useCancelAsyncFn",
            "type": "useCancelAsyncFn<T>(fn: (ctx: CancelContext) => Promise<T>, deps) => AsyncFnReturn",
            "desc": "同 useAsyncFn，但回调收到取消上下文；组件卸载或重复调用时中断前一次请求。",
            "optional": false
          },
          {
            "name": "usePolling",
            "type": "usePolling<T>(service, options?) => { data, loading, error, start, stop, state }",
            "desc": "按间隔轮询一个异步服务，支持成功/失败回调与手动起停。",
            "optional": false
          },
          {
            "name": "useHtAxios",
            "type": "useHtAxios({ config, requestInterceptorsCallback, ... }) => { get, post, del, put }",
            "desc": "带拦截器的 axios 实例，统一注入请求头与错误处理。",
            "optional": false
          }
        ]
      },
      {
        "title": "DOM 观察",
        "interfaceName": "hooks",
        "note": "尺寸、可见性与设备像素比，SSR 安全。",
        "rows": [
          {
            "name": "useElementSize",
            "type": "useElementSize(containerRef: any, options?: ResizeObserverOptions) => { width: number; height: number; }",
            "desc": "订阅元素尺寸，内部走 ResizeObserver。",
            "optional": false
          },
          {
            "name": "useResizeObserver",
            "type": "useResizeObserver(containerRef: any, cb: ResizeObserverCallback, options?: ResizeObserverOptions) => void",
            "desc": "更底层的 ResizeObserver 封装，自己拿 entry 做事。",
            "optional": false
          },
          {
            "name": "useInView",
            "type": "useInView(options?: IntersectionObserverInit, triggerOnce?: boolean) => [TargetRef, boolean]",
            "desc": "元素进入视口时置 true，可只触发一次（懒加载常用）。",
            "optional": false
          },
          {
            "name": "useDevicePixelRatio",
            "type": "useDevicePixelRatio() => { pixelRatio }",
            "desc": "SSR 初值为 1，挂载后同步真实 DPR 并监听变化（canvas 高清必备）。",
            "optional": false
          }
        ]
      },
      {
        "title": "存储",
        "interfaceName": "hooks",
        "note": "三种持久化介质，同一套读写签名。",
        "rows": [
          {
            "name": "useLocalStorage",
            "type": "useLocalStorage<T>(key: string, initialValue?: T, options?: ParserOptions<T>) => [T | undefined, Setter<T>, Remover]",
            "desc": "localStorage 持久化，可自定义序列化器。",
            "optional": false
          },
          {
            "name": "useSessionStorage",
            "type": "useSessionStorage<T>(key: string, initialValue?: T, raw?: boolean) => [T | undefined, Setter<T>, () => void]",
            "desc": "sessionStorage 持久化，用法同 useLocalStorage，但作用域限于当前标签页。",
            "optional": false
          },
          {
            "name": "useCookie",
            "type": "useCookie(key, options?, defaultValue?) => [value, set]",
            "desc": "基于 js-cookie，可带 expires / path 等属性。",
            "optional": false
          }
        ]
      },
      {
        "title": "交互",
        "interfaceName": "hooks",
        "note": "倒计时、无限滚动、长连接与图片预载。",
        "rows": [
          {
            "name": "useCountDown",
            "type": "useCountDown() => [number, (num?: number) => void, () => void]",
            "desc": "秒级倒计时，验证码按钮那类场景。",
            "optional": false
          },
          {
            "name": "useInfiniteScroll",
            "type": "useInfiniteScroll<T>({ dataSource, fetchData, pageSize, ... }) => { data, loading, hasMore, loadMore, reset }",
            "desc": "分页累积加载，自带 loading 与到底判断。",
            "optional": false
          },
          {
            "name": "useWebSocket",
            "type": "useWebSocket(url, options?) => { readyState, sendMessage, connect, disconnect, latestMessage }",
            "desc": "WebSocket 连接与消息收发，带 open/close/error 回调。",
            "optional": false
          },
          {
            "name": "useImageLoad",
            "type": "useImageLoad({ imgList }: { imgList: string[]; }) => (string | boolean | string[])[]",
            "desc": "批量预载图片，全部就绪后再渲染，避免闪烁。",
            "optional": false
          }
        ]
      },
      {
        "title": "工具",
        "interfaceName": "hooks",
        "note": "上一次的值、深比较依赖、窗口尺寸与状态容器。",
        "rows": [
          {
            "name": "usePrevious",
            "type": "usePrevious<T>(value: T) => T | undefined",
            "desc": "返回上一次渲染时的值,首次渲染返回 undefined。",
            "optional": false
          },
          {
            "name": "useWindowSize",
            "type": "useWindowSize() => { width, height }",
            "desc": "SSR-safe window size hook。\n- SSR 环境返回 { width: 0, height: 0 }\n- 客户端首帧通过 useEffect 同步真实尺寸",
            "optional": false
          },
          {
            "name": "useDeepCompareEffect",
            "type": "useDeepCompareEffect(effect: EffectCallback, deps: DependencyList) => void",
            "desc": "依赖做深比较而非引用比较，省去手动 memo 对象依赖。",
            "optional": false
          },
          {
            "name": "createContainer",
            "type": "createContainer(useHook) => { Provider, useContainer, withContainer, Context }",
            "desc": "把任意 hook 提升为 Context 容器，跨组件共享状态。",
            "optional": false
          }
        ]
      }
    ]
  }
];
