## Why

`/front` 展示 heitu 组件库的四个 tab 都只有可运行 demo，**没有字段说明**——观众看得到效果，
看不到「这个参数叫什么、什么类型、干什么用」。而说明其实早就写好了：heitu 的
`node_modules/heitu/dist/**/*.d.ts` 完整保留了中文 TSDoc（已验证），只是从没被搬到页面上。

唯一的例外 `app/front/demos/hooks-reference.ts` 恰好说明了不该怎么做：165 行手抄，文件头自称
「与当前安装版本一致」——这是一句**没有任何东西守着的断言**，而 heitu 已经升过一次级（`d1f2807`）。
照这个模式再抄三份，等于把这笔债乘以四。

## What Changes

- 新增构建脚本，从 `node_modules/heitu/dist/**/*.d.ts` 用 TypeScript AST 提取字段名、类型、TSDoc
- 新增**策展清单 + 说明覆盖层**（人写）：声明每个 tab 展示哪些接口的哪些字段，并为源里没有
  TSDoc 的字段补中文说明
- 新增**生成物**（脚本写）：清单与提取结果 join 后的最终数据，页面直接消费
- 四个 tab（FormRender / Charts / Canvas / Hooks）挂上字段说明展示位
- **改造 `app/front/demos/hooks-reference.ts`**：`signature` 改为从 `.d.ts` 提取，人工润色过的
  `desc` 迁入覆盖层。这 165 行不是被删除，是被拆成「自动的一半」和「人写的一半」
- 新增 `npm run gen:reference`，并在 CLAUDE.md 记入「升级 heitu 后必须重跑」

不涉及 breaking change：`/front` 之外的路由、鉴权、数据层一律不动。

## Capabilities

### New Capabilities

- `heitu-field-reference`: `/front` 各 tab 的字段说明——展示范围如何界定、说明从哪里来、
  以及 heitu 升级导致内容漂移时生成流程必须如何失败

### Modified Capabilities

（无。`openspec/specs/` 目前为空，本 change 是第一个。）

## Impact

**新增**

- `scripts/gen-heitu-reference.mjs` —— 提取 + join + 校验，与 `scripts/migrate.mjs` 同处一层
- `app/front/reference/curation.ts` —— 手写：策展清单 + 说明覆盖层
- `app/front/reference/generated.ts` —— 脚本生成，**不要手改**（沿用 `app/fonts.css` 的既有约定）

**改动**

- `app/front/demos/hooks-reference.ts` —— 拆解，`desc` 迁往 `curation.ts`
- `app/front/demos/*.tsx` 四个 demo —— 挂载展示位
- `package.json` —— 新增 `gen:reference` script
- `CLAUDE.md` —— 记入重跑约定与该约定目前无自动强制

**依赖**

- `typescript`（已是 devDependency）被脚本用作运行时 AST 解析器，不新增依赖
- 数据源是 `node_modules/heitu/dist`，**不跨仓引用 `../heitu-platform`**：peco-platform
  在容器里构建时拿不到隔壁仓库，只有 npm 包是可靠的

**已知缺口（有意接受，非遗漏）**

本仓库没有 CI（无测试框架、无 `.github/workflows`）。因此漂移守卫**只在有人执行脚本时生效**，
`npm update heitu` 后无人重跑的话页面会静默陈旧——与 `hooks-reference.ts` 今天的处境同类，
区别只在于这次「跑一下就能发现」。橱窗场景下接受此代价；若日后要开第一个 CI workflow，
本 change 提供了一个失败条件明确、易于自动判定的起点。
