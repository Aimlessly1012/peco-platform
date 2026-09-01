import type { TabKey } from "../nav";

/**
 * `/front` 字段说明的类型契约（M15）。
 *
 * 三个文件的分工：本文件定契约，`curation.ts` 由人手写，`generated.ts` 由脚本生成。
 * 契约单独抽出来，是为了让脚本只需生成数据——改产物结构时不必动脚本里的模板字符串。
 */

// ── 人写的一侧 ────────────────────────────────────────────────────────

/**
 * 一张字段表的来源与展示范围。
 *
 * `fields` 是白名单而非黑名单：heitu 的 canvas 模块有 274 个成员行，大半是
 * `calcWholeRingD()`、`deg2rad()` 一类 class 上的内部方法，全量提取会把它们倒进橱窗页面。
 * 判据是声明位置不是名字：`Circle` 的 `path2D` 是内部缓存（不展示），
 * `ICustom` 的 `path2D` 是必填构造参数（必须展示）。
 * 取值边界是「该 tab 的 demo 里实际出现过的字段」——演示了什么就解释什么。
 */
export interface MemberGroup {
  kind?: "members";
  /** 表标题，如「FormRender Props」「图表通用配置」 */
  title: string;
  /** 源接口在 .d.ts 中的声明名，如 `IFormRenderProps` / `ICircle` */
  interfaceName: string;
  /** 展示的字段，**数组顺序即页面呈现顺序** */
  fields: string[];
  /**
   * 继承来源的一行说明，如「其余继承 antd `FormProps`」。
   * 继承字段一律不展开：展开 `FormProps` 会带入 antd 数十个字段，
   * 四种图表展开 `IChartConfig` 则会让十余行公共配置重复四遍。
   */
  inheritedFrom?: string;
  /** 表下方的补充说明 */
  note?: string;
}

/**
 * 函数清单形态（M15 补充）——hooks 那一类。
 *
 * 与 `MemberGroup` 的区别是本质的：hooks 不是「一个接口的若干字段」，而是 19 个
 * `declare function`，各自散在 `hooks/useXxx/index.d.ts` 里，没有共同的宿主接口。
 * 硬塞进 interfaceName + fields 的模型会要求虚构一个不存在的接口名。
 *
 * 产物侧两者仍统一为 `FieldTable`：members 的行是「字段名 / 类型 / 说明」，
 * functions 的行是「函数名 / 签名 / 说明」，页面不必分支。
 */
export interface FunctionGroup {
  kind: "functions";
  title: string;
  /** 搜索范围，dist 下的相对目录，如 `"hooks"` */
  from: string;
  /** 函数名。沿用 `fields` 而非另起名字，是为了让脚本与页面统一访问 */
  fields: string[];
  note?: string;
}

/**
 * 一张表的来源。默认是 `MemberGroup`（`kind` 省略即可），hooks 用 `FunctionGroup`。
 *
 * 做成联合类型而非给 `MemberGroup` 加可选字段，是要让 tsc 强制脚本分别处理两种形态：
 * functions 形态下 `interfaceName` 根本不存在，可选字段会让「忘了处理」变成运行时才炸。
 */
export type CurationGroup = MemberGroup | FunctionGroup;

export interface CurationTab {
  tab: TabKey;
  groups: CurationGroup[];
}

/**
 * 说明覆盖层：键为 `接口名.字段名`。
 *
 * 键的形状不是随意约定——它同时充当漂移探针。脚本据此校验「点名的接口还在吗」
 * 「点名的字段还在吗」，heitu 改名或删字段时会失败而非静默跳过。
 * 模板字面量类型让漏写接口名前缀（写成 `"radius"`）在类型层面就被拦下。
 */
export type OverrideMap = Record<`${string}.${string}`, string>;

/**
 * 签名覆盖层：键为 `${from}.${函数名}`，**仅用于 functions 形态**。
 *
 * 为什么签名也需要人写：机器提取保证的是「不遗漏、不腐烂」，不是「最适合展示」。
 * `useHtAxios` 的完整签名 814 字符（手写版 78），在三列表格里要占七八行、撑垮整张表。
 * 省略哪些噪音、把返回值缩成 `{ get, post, ... }`，是人的判断，脚本给不出不武断的规则。
 *
 * 守卫一条不减：函数是否存在、是否改名、是否消失，仍全部由脚本按 `fields` 校验——
 * 那才是旧 hooks-reference.ts 真正缺的东西。这里让渡的只是签名的**文本呈现**。
 */
export type SignatureMap = Record<`${string}.${string}`, string>;

// ── 脚本生成的一侧 ────────────────────────────────────────────────────

/** 字段表里的一行。不设「默认值」列：heitu 未用 `@default` 标签，默认值写在描述文本内。 */
export interface FieldRow {
  name: string;
  /** 类型文本，取自 .d.ts 原样，不做展开或简化 */
  type: string;
  /**
   * 说明。来源优先级：**人写的覆盖层 → 源 TSDoc**（D11 已将方向反转）。
   * 覆盖层的存在即代表人做过判断，故优先；不写则自动取源文本。
   * 两处皆无时脚本已失败退出，不会走到这里。
   */
  desc: string;
  /** 声明中带 `?` */
  optional: boolean;
}

export interface FieldTable {
  title: string;
  interfaceName: string;
  inheritedFrom?: string;
  note?: string;
  rows: FieldRow[];
}

export interface ReferenceTab {
  tab: TabKey;
  tables: FieldTable[];
}
