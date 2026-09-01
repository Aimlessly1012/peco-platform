## 1. 契约先行（完成后第 5、6、7 组即可与第 2 组并行）

- [x] 1.1 在 `app/front/reference/types.ts` 定义类型契约：策展清单项（tab / 接口名 / 字段名列表 / 继承来源）与覆盖层（键为模板字面量类型 `` `${string}.${string}` ``，漏写接口名前缀在类型层即被拦下）；`curation.ts` 建空骨架，文件头写明**只能有 type-only import**（见 D9）
- [x] 1.2 `app/front/reference/generated.ts` 建占位并标注「脚本生成，不要手改」，与 `app/fonts.css` 的既有约定一致；产物结构定义在 `types.ts` 的 `ReferenceTab` / `FieldTable` / `FieldRow`，脚本因而只需生成数据

## 2. 提取脚本

- [x] 2.1 新建 `scripts/gen-heitu-reference.mjs`：用 `ts.createSourceFile` 解析 `node_modules/heitu/dist/**/*.d.ts`（排除 `esm/` 副本），按接口名定点提取字段的名称、类型文本与 TSDoc，不启用 TypeChecker；读取 `curation.ts` 用 `ts.transpileModule` + `data:` URL 动态 import（D9，已实测可行）
- [x] 2.2 实现 join：TSDoc 优先，其次覆盖层。**声明形态需收三种**——`InterfaceDeclaration`（多数）、`ClassDeclaration`（`Group`）、`TypeAliasDeclaration` 且类型为 TypeLiteral（`AnimateCartoonConfig`）；另需支持非 export 声明（`ICircle` 未导出，AST 层面仍可见）。只认 interface 会让 Canvas 两张表直接失败（后端 6.x 查证时发现，脚本已实现）
- [x] 2.3 实现三条失败路径，均以非零码退出并指明接口名与字段名：点名的接口不存在、点名的字段不存在、字段两处皆无说明
- [x] 2.4 实现冗余提示：覆盖层条目对应字段在源里已有 TSDoc 时输出提示，且**不使脚本失败**
- [x] 2.5 幂等写入 `generated.ts`；确认脚本任何路径下都不写 `curation.ts`
- [x] 2.6 `package.json` 增加 `"gen:reference": "node scripts/gen-heitu-reference.mjs"`

## 3. FormRender 垂直切片（用覆盖率最高的模块验证整条通路）

- [x] 3.1 清单填入 `IFormRenderProps`、`IItem`、`INodeProps`，范围限定为 `FormRenderDemo` 里实际出现过的字段
- [x] 3.2 执行 `npm run gen:reference`，确认**零覆盖条目**也能生成完整说明（该模块 TSDoc 覆盖率 97%）
- [x] 3.3 `FormRenderDemo.tsx` 挂载展示位，确认三列（字段名 / 类型 / 说明）渲染正常、无「默认值」列
- [x] 3.4 确认 `IFormRenderProps` 只列自有字段，并有一行「其余继承 antd `FormProps`」，未展开 antd 字段

## 4. 守卫验证（本仓库无测试框架，以下为手工执行；每条对应 spec 中一个 scenario）

> 必须在铺开其余三个 tab **之前**完成——守卫若不成立，方案的核心价值不存在，越晚发现返工越大。
> 每条验证后务必将临时改动还原。

- [x] 4.1 临时在清单点名一个不存在的接口 → 确认脚本非零退出并报出接口名
- [x] 4.2 临时把某个字段名改成不存在的拼写 → 确认脚本非零退出并报出 `接口名.字段名`
- [x] 4.3 临时点名一个既无 TSDoc 又无覆盖的字段 → 确认脚本以「缺说明」非零退出
- [x] 4.4 临时为一个已有 TSDoc 的字段添加覆盖条目 → 确认输出「可删除」提示且脚本**成功**退出
- [x] 4.5 补写若干覆盖条目后重跑脚本 → 确认 `curation.ts` 逐字节未变（`git diff --stat` 只显示 `generated.ts`）
- [x] 4.6 临时重命名 `../heitu-platform` 或在其不可达的路径下执行 → 确认脚本正常完成，无路径错误

## 5. Charts

- [x] 5.1 清单按 D5 拆分：四种图表各列自有字段，`IChartConfig` 公共字段单列一张「图表通用配置」表
- [x] 5.2 补写约 10 条覆盖（该模块 TSDoc 覆盖率 76%，缺口集中在 `width` / `height` / `data` / `colors` / `tooltip` / `legend` 等公共配置）
- [x] 5.3 `ChartsDemo.tsx` 挂载展示位

## 6. Canvas（需 canvas 引擎领域知识，勿凭字段名臆测）

> 本组是唯一的真活儿，约 35 条覆盖全为新写。**错误的说明比空白更有害**：空白会被脚本拦下，
> 错的说明会原样上线。不确定的取值必须查证 `../heitu-platform/packages/heitu/src` 源码或实测。

- [x] 6.1 逐条比对 `CanvasDemo.tsx`，圈定六种图元 + Stage + Animate 中**实际被演示过**的字段，写入清单
- [x] 6.2 查证 `ICircle.border: 0 | 1 | 2` 三个取值的确切语义后再写入覆盖（design.md 的 Open Questions 记录了此项）
- [x] 6.3 补写其余覆盖条目
- [x] 6.4 `CanvasDemo.tsx` 挂载展示位

## 7. Hooks 拆解

- [x] 7.1 将 `hooks-reference.ts` 的 `desc` 逐条迁入覆盖层，并与源 TSDoc 逐条比对**取优**（判据：面向使用者的说明 > 面向实现者的说明）；被 TSDoc 取代的条目从 OVERRIDES 删除，不留冗余。所有说明须自包含，不得以「同上」依赖相邻行（见 D7 实施修正）
- [x] 7.2 清单点名 19 个 hook，`signature` 改由脚本从 `.d.ts` 提取
- [x] 7.3 删除 `hooks-reference.ts` 中已被生成物取代的部分；确认 `HooksDemo.tsx` 的「全部 API」一节改为消费 `generated.ts`
- [x] 7.4 比对迁移前后的页面输出，确认签名与说明无丢失、无降级

## 8. 收口

- [x] 8.1 `CLAUDE.md` 增补：升级 heitu 后必须执行 `npm run gen:reference`，并写明该约定**目前无自动强制**（仓库无 CI）
- [x] 8.2 `npm run lint` 与 `npm run build` 通过
- [x] 8.3 四个 tab 逐一手工验收：无空白说明、无 class 内部方法泄漏（如 `calcRingD()`、`deg2rad()`）、继承未展开。**判据是声明位置不是名字**：别误删 `ICustom.path2D`，它是必填构造参数，与 `Circle` 上那个同名内部缓存性质不同
- [x] 8.4 `generated.ts` 已随 commit 28ba690 入库（736 行）。注：本次为新增文件，「diff 中字段变化可读」要到下一次 heitu 升级才真正得到验证；且本次提交混入了 108 行无关的格式化改动，一定程度上冲淡了该可读性
- [x] 8.5 结果验证：`OVERRIDES` / `SIGNATURES` 中人写 N 条，产物中必须命中 N 条，未命中逐条列出并非零退出。**放在主流程默认执行**，而非仅 `--check`——R5 两次事故都发生在日常 `gen:reference` 时，只在需要主动调用的模式里生效等于把防线交给记性。`--check`（`npm run check:reference`）额外多验一层「产物是否最新」。孤儿键一并升为错误：键名拼错与「留着备用」在文件里无法区分，而拼错的代价是说明静默失效
