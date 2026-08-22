/**
 * heitu hooks 速查表（M12 补充任务）。
 *
 * 签名照抄自 node_modules/heitu/dist/hooks/**\/*.d.ts，与当前安装版本一致；
 * 有交互 demo 的条目在 UI 上会标出来，其余靠这张表列全。
 */

export interface HookEntry {
  name: string;
  signature: string;
  desc: string;
  /** 本页有可交互演示 */
  demo?: boolean;
}

export interface HookGroup {
  key: string;
  label: string;
  hint: string;
  items: HookEntry[];
}

export const HOOK_GROUPS: HookGroup[] = [
  {
    key: "async",
    label: "数据请求",
    hint: "异步状态机、可取消请求、轮询与 axios 实例",
    items: [
      {
        name: "useAsyncFn",
        signature: "useAsyncFn<T>(fn, deps?, initialState?) => [AsyncState<T>, T]",
        desc: "把异步函数包成 { loading, value, error } 状态机，手动触发。",
        demo: true,
      },
      {
        name: "useCancelAsyncFn",
        signature: "useCancelAsyncFn<T>(fn: (ctx: CancelContext) => Promise<T>, deps) => AsyncFnReturn",
        desc: "同上，但回调收到取消上下文；组件卸载或重复调用时中断前一次请求。",
      },
      {
        name: "usePolling",
        signature: "usePolling<T>(service, options?) => { start, stop, ... }",
        desc: "按间隔轮询一个异步服务，支持成功/失败回调与手动起停。",
        demo: true,
      },
      {
        name: "useHtAxios",
        signature: "useHtAxios({ config, requestInterceptorsCallback, ... }) => { get, post, ... }",
        desc: "带拦截器的 axios 实例，统一注入请求头与错误处理。",
      },
    ],
  },
  {
    key: "dom",
    label: "DOM 观察",
    hint: "尺寸、可见性与设备像素比，SSR 安全",
    items: [
      {
        name: "useElementSize",
        signature: "useElementSize(ref, options?) => { width, height }",
        desc: "订阅元素尺寸，内部走 ResizeObserver。",
        demo: true,
      },
      {
        name: "useResizeObserver",
        signature: "useResizeObserver(ref, cb, options?) => void",
        desc: "更底层的 ResizeObserver 封装，自己拿 entry 做事。",
      },
      {
        name: "useInView",
        signature: "useInView(options?, triggerOnce?) => [ref, inView]",
        desc: "元素进入视口时置 true，可只触发一次（懒加载常用）。",
        demo: true,
      },
      {
        name: "useDevicePixelRatio",
        signature: "useDevicePixelRatio() => { pixelRatio: number }",
        desc: "SSR 初值为 1，挂载后同步真实 DPR 并监听变化（canvas 高清必备）。",
        demo: true,
      },
    ],
  },
  {
    key: "storage",
    label: "存储",
    hint: "三种持久化介质，同一套读写签名",
    items: [
      {
        name: "useLocalStorage",
        signature: "useLocalStorage<T>(key, initialValue?, options?) => [value, set, remove]",
        desc: "localStorage 持久化，可自定义序列化器。",
        demo: true,
      },
      {
        name: "useSessionStorage",
        signature: "useSessionStorage<T>(key, initialValue?, raw?) => [value, set, remove]",
        desc: "同上，作用域是当前标签页。",
      },
      {
        name: "useCookie",
        signature: "useCookie(key, options?, defaultValue?) => [value, set]",
        desc: "基于 js-cookie，可带 expires / path 等属性。",
      },
    ],
  },
  {
    key: "interaction",
    label: "交互",
    hint: "倒计时、无限滚动、长连接与图片预载",
    items: [
      {
        name: "useCountDown",
        signature: "useCountDown() => [count, start(num?), stop()]",
        desc: "秒级倒计时，验证码按钮那类场景。",
        demo: true,
      },
      {
        name: "useInfiniteScroll",
        signature: "useInfiniteScroll<T>({ dataSource, pageSize, fetchData, ... }) => { loadMore, reset, ... }",
        desc: "分页累积加载，自带 loading 与到底判断。",
      },
      {
        name: "useWebSocket",
        signature: "useWebSocket(url, options?) => { sendMessage, ... }",
        desc: "WebSocket 连接与消息收发，带 open/close/error 回调。",
      },
      {
        name: "useImageLoad",
        signature: "useImageLoad({ imgList }) => [loaded, ...]",
        desc: "批量预载图片，全部就绪后再渲染，避免闪烁。",
      },
    ],
  },
  {
    key: "util",
    label: "工具",
    hint: "上一次的值、深比较依赖、窗口尺寸与状态容器",
    items: [
      {
        name: "usePrevious",
        signature: "usePrevious<T>(value) => T | undefined",
        desc: "拿到上一次渲染时的值，做差异判断。",
        demo: true,
      },
      {
        name: "useWindowSize",
        signature: "useWindowSize() => { width, height }",
        desc: "窗口尺寸，SSR 安全。",
        demo: true,
      },
      {
        name: "useDeepCompareEffect",
        signature: "useDeepCompareEffect(effect, deps)",
        desc: "依赖做深比较而非引用比较，省去手动 memo 对象依赖。",
      },
      {
        name: "createContainer",
        signature: "createContainer(useHook) => { Provider, useContainer, withProvider }",
        desc: "把任意 hook 提升为 Context 容器，跨组件共享状态。",
      },
    ],
  },
];

export const HOOK_COUNT = HOOK_GROUPS.reduce((n, g) => n + g.items.length, 0);
