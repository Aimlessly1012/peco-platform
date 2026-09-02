## Context

前置：merge-rag-backend 已把全栈收进单仓（`services/` + `deploy/` + 统一 CI）。
本 change 解决「第 N 个项目怎么进来」。

现状的散改点（每新增一个项目都要碰的地方）：TopBar 硬编码三个链接；首页项目卡片硬编码；
middleware matcher 四条手写（且 `6eaef3d` 的裸路径陷阱每次重复）；nginx 主配置文件；
compose；鉴权契约只在未入库的 CLAUDE.md。

硬约束：**Next 要求 `config.matcher` 是静态字面量**，不能从注册表计算——这条决定了守卫的
形态（校验而非生成）。

## Goals / Non-Goals

**Goals:**

- 新增项目 = 新增文件（nginx conf、compose yml、`app/<name>/`、可选 `services/<name>/`）
  + 三处登记（注册表一行、matcher 两行、compose include 一行），**三处全部有机器守卫**
- 「登录直走一套」成为版本库里的正式契约，任何语言的新后端照 spec 验签即可接入
- 访问级别（public / approved / admin）在注册表声明一次，middleware 与项目后端各自执行

**Non-Goals:**

- 不做动态路由注册 / 插件系统——注册表是类型化数组，不是框架
- 不改 RAG 后端行为（删空密钥回退归 change C）
- 不动数据拓扑（`platform_users` 的家、数据库-每项目约定的落地细节归阶段三）
- 不重构 `lib/` 服务端客户端混放、组件放置标准——另立 change

## Decisions

### D1：注册表是数据不是框架

`lib/projects.ts` 导出一个类型化数组，字段：`key`（目录名/路由前缀）、`label`、`route`、
`access: "public" | "approved" | "admin"`、`backend: boolean`，及可选 `showcase`
（首页作品卡片文案：name/tagline/stack/highlights…）。TopBar、首页、middleware 判断逻辑
三处消费。抽象到此为止——再往上（动态加载、配置文件、注册中心）都是为不存在的规模付费。
**上限约束的是机制复杂度，不是字段数量**：showcase 是数据增补不是机制增补；无 showcase
的条目不进作品区（内部工具与作品的区分由此天然成立，不需要额外的布尔开关）。

### D2：matcher 静态限制 → 守卫脚本，哲学同 check:reference

matcher 无法从注册表生成（Next 静态解析），所以每个受保护项目仍要手写两行——而裸路径
陷阱恰好藏在这两行里。`scripts/check-middleware.mjs` 解析 middleware.ts 的 matcher 数组，
比对注册表：凡 `access ≠ public` 的项目，`/<route>` 与 `/<route>/:path*` 两条缺一即非零退出，
输出「缺哪个项目的哪一条」。接入 CI 后，同一个坑不再靠记性防守。

与 heitu change 的 `check:reference` 同一哲学：**改既有文件的地方必须有守卫盯着，
新增文件的地方靠结构保证不了错**。

### D3：nginx include 化——新增项目=新增文件

`deploy/nginx/nginx.conf` 只留全局与 `include projects/*.conf`；`projects/rag.conf` 承载
`/rag/api` 剥前缀转发。新项目一个 conf 文件即生效，不碰主文件。compose 侧 A 已经做到
按项目一个文件。

### D4：访问级别双层执行，matcher 只列受保护项目

middleware 的**判断逻辑**可以动态读注册表（只有 matcher 必须静态）：approved 校验
`status === "approved" && !disabled`，admin 追加 `role === "admin"`，public 项目不进 matcher。
项目后端仍自行验 JWS——middleware 是体验层不是防线，这条既有原则（CLAUDE.md 三层访问控制）
原样适用于所有新项目。

### D5：登录契约入 spec，fail-loud 条款留给 C

`project-onboarding` spec 本次写入：唯一登录 UI、禁止自建鉴权、JWS 验签参数
（HS256 / `githubId` / `role` / `status`）、七步接入清单。「验签密钥缺失必须拒绝启动」
的条款**由 change C 以 delta 追加**——因为 RAG 现存「空密钥退回密码登录」的行为与之矛盾，
spec 先行断言会造成规格与现实的已知偏差；C 删回退与加条款同 change 落地，规格与现实同步翻转。

## Risks / Trade-offs

**R1：注册表与 `app/<name>/` 目录可能失配**（注册了但目录不存在、或反之）→ 守卫脚本顺带
校验注册表 `route` 对应的 `app/` 目录存在性；反向（目录存在未注册）仅提示不报错——
允许开发中的项目先不上导航。

**R2：守卫解析 middleware.ts 依赖其书写形态**（正则/AST 对 matcher 数组的提取）→ 用
TypeScript AST 提取（`typescript` 已是依赖，同 gen-heitu-reference 的路子），不用正则；
matcher 写法超出可解析形态时守卫直接失败——宁可误报也不静默放过。

**R3：public 项目不进 matcher，意味着它们完全绕过 middleware** → 这是现状语义的延续
（`/front` 今天就不在 matcher），风险是若某 public 项目日后要加登录墙，改注册表却忘改
matcher——正是守卫脚本覆盖的场景，闭环成立。

**实施记录（第 1 组自查，b556f64）——一类新的失效：防线静默降级。** middleware 读注册表
的首版写成 `!project || access === "public"` 即放行，「matcher 有、注册表无」的路径被完全
敞开。它与 Set 遮蔽 / REPO_ROOT / YAML anchor 不同类：那三例是**功能静默失效**，这一例是
**防线静默降级**——一切功能照常、重定向照常、守卫照常通过，只有保护范围悄悄缩小，任何
测试都不会表现，除非恰好构造出那个组合。

成因结构更值得记：check:middleware 对该组合**特意**只提示不报错（可能是开发中项目），
运行时又放行——**两层各自留的例外正好对齐时，例外就成了洞**。修复原则：能进 middleware
的路径必然在 matcher 里，有人写它进去就是想保护它，登记遗漏的正确默认是多挡一层不是敞开。

这是平台第三处「失效方向朝关」的设计（`lib/auth.ts` DB 失联降级拒绝、compose 基线无端口、
此处未知即拦）——方向一致性至此已是这个代码库的约定，不再是巧合。

**实施记录（第 4 组回滚盲区）**：dry-run 的回滚核对只盯了源文件，漏了构建产物——
`.next/types` 里为假想项目生成的类型桩引用已删除的模块，而 tsconfig include 它，于是
**回滚当时所有检查全绿，下一次 tsc 才炸**，报错还指向一个没人写过的文件（第一反应会当成
缓存坏了）。这是又一种失效形态：**延迟一步才响**——介于「响」与「哑」之间，响在错误的
时间、指向错误的位置。口径修正：跑过 build 的 dry-run，回滚必须连 `.next` 一起核对或清除。

**实施记录（第 3 组）**：projects 片段目录不能落在 `/etc/nginx/conf.d/`——那里的文件被
nginx 当 http 块顶层配置加载，location 片段会让容器**直接起不来**。这个坑与静默失效那批
性质相反（它是响的），危险在于伪装：它长得像个无所谓的路径选择题（「反正都是挂配置，
conf.d 顺手」），而 conf.d 恰好是唯一不能选的答案。已升为 spec 的规范性约束，并须写进
接入清单——**响的坑写进清单是为了省排查时间，哑的坑写进清单是为了能被发现**，两类都值得写，
理由不同。

**实施记录（第 4 组 dry-run）**：「新增项目零编辑既有文件」被证伪——nginx 的 `include`
支持通配（丢文件即生效），**Docker Compose 的 `include` 不支持**（实测把 `compose/*.yml`
当字面路径 open 报错），伞文件必须手工加一行。处置采「把发现变成守卫」：登记点从两处改为
三处，`check:middleware` 扩展校验「`backend: true` 的项目其 `deploy/compose/<key>.yml`
存在且被伞文件 include」——至此三处登记全部有机器盯守，漏任何一处都会响。dry-run 的价值
正在于此：它不是走流程，是拿真实操作去磨 spec 的断言。

另：接入清单为每步标注了「漏了会怎样 + 有无机械检查」——让人一眼看出哪几步靠自觉。
compose 步随本次守卫扩展从「无机械检查」转为有；其余无机械检查的步（后端目录、nginx conf、
JWS 验签）保持如实标注，不假装有兜底。

**实施记录（第 2 组）**：GitHub Actions 的 `paths` 过滤是 **workflow 级不是 job 级**，
因此 CI 按项目拆文件（`ci.yml` / `ci-platform.yml`）是唯一能各管各触发的形态——顺带把
「新项目=新文件」延伸到了 CI 层。另：Actions 的 YAML **不支持 anchor/alias 且静默失效**
（不报错，paths 直接不过滤，workflow 退化成每次 push 都跑）——与 Set 遮蔽、REPO_ROOT
同属「不崩不红只是不干活」一类，已用逐字重复 + 注释规避，记档。

## Open Questions

- 首页项目卡片的视觉形态（沿用现有卡片还是重排）——不阻塞数据层，实现时看现有样式定。
- 下一个真实项目是什么、什么语言后端——spec 的验签示例目前只有 Python 一份实现，
  第二种语言出现时接入清单可能需要补一节示例。
