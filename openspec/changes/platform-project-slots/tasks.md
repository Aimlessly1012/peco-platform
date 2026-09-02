## 1. 注册表与消费方

- [x] 1.1 `lib/projects.ts`：类型定义 + 现有项目登记（front=public 无后端、rag=approved 有后端、admin=admin 无后端；首页/login/pending 属平台壳不入表）
- [x] 1.2 `components/TopBar.tsx` 改为从注册表渲染导航。「视觉不变」的确切含义：平台壳条目（首页）保留原样 + 项目条目来自注册表；`approved` 项目对 pending 用户**仍可见**（access 管进入不管可见性，见 spec），仅 `admin` 项目对非管理员隐藏（既有 `adminOnly` 行为保留）；项目条目的 active 统一推导 `p === route || p.startsWith(route + "/")`，首页条目的 `p === "/"` 特判保留
- [x] 1.3 首页项目区改为从注册表渲染（视觉形态实现时按现有样式定，见 design Open Question）
- [x] 1.4 `middleware.ts` 判断逻辑读注册表执行三级访问（matcher 保持静态手写，本任务只核对现有四条与注册表一致）

## 2. 守卫脚本

- [x] 2.1 `scripts/check-middleware.mjs`：TS AST 提取 matcher 数组（不用正则），比对注册表——非 public 项目缺裸路径或 `:path*` 任一条即非零退出并指明；matcher 写法超出可解析形态时直接失败而非静默放过
- [x] 2.2 顺带校验：注册表 `route` 对应的 `app/` 目录存在（缺失报错）；目录存在未注册仅提示
- [x] 2.3 `package.json` 加 `check:middleware`；CI 采用**独立 `ci-platform.yml`** 而非往 `ci.yml` 加 job——GitHub 的 paths 过滤是 workflow 级不是 job 级，拆文件是唯一能「平台改动只跑平台、rag 改动只跑 rag」的形态；check:middleware 与 check:reference 均已入 CI，R1「约定无强制」到此闭合
- [x] 2.4 回归验证（哲学同 m15 的 8.5，注入缺陷确认守卫会响）：临时删掉 matcher 一条裸路径 → 非零退出且指明；恢复 → 零退出；全程用副本或还原，不留改动

- [x] 2.5 守卫扩展（第 4 组 dry-run 证伪「零编辑伞文件」后追加）：`check:middleware` 增加校验——注册表 `backend: true` 的项目，`deploy/compose/<key>.yml` 存在且被伞文件 include，缺失非零退出并指明缺文件还是缺 include 行；注入式回归（删 include 行 → 响；删 compose 文件 → 响；恢复 → 静）；接入清单 compose 步的标注从「无机械检查」改为有

## 3. nginx 槽位化

- [x] 3.1 `deploy/nginx/nginx.conf` 拆出 `include projects/*.conf`；`projects/rag.conf` 承载现有 `/rag/api` 剥前缀规则，行为逐字节等价
- [x] 3.2 本地全栈（nginx 挂 3000、`projects/rag.conf` 由独立目录 include）真流量验证：用户登录态下 chat 回答**逐字流出**、`[n]` 引用可跳右栏代码；`/ask` 经 nginx 200 / 9.5KB。conf.d 拆分后的 SSE 六件套在真实流量下成立，与拆分前行为一致

## 4. 接入清单与文档

- [x] 4.1 七步接入清单落入 `project-onboarding` spec 所指的文档位置（README 一节 + spec 本体），与守卫校验范围逐条对齐
- [x] 4.2 用一个假想项目 dry-run 清单：只新增文件 + 注册表一行 + matcher 两行，守卫/lint/build 全绿后回滚——验证「新增项目仅新增文件」成立。**回滚口径含构建产物**：dry-run 中跑过 build 的，回滚核对必须带上 `.next`（或直接清掉）——`.next/types` 里的类型桩会引用已删除的页面模块，tsconfig 又 include 它，结果是回滚当时全绿、下一次 tsc 才炸，且报错指向没人写过的文件（已实踩）

## 5. 收口

- [x] 5.1 `npm run lint`、`npm run build`、`check:middleware`、`check:reference` 全绿
- [x] 5.2 手工验收全部完成：导航/首页入口 ✓；**真实登录态**的访问级别验证——把用户自己的行临时翻成 pending → `/rag` 落 `/pending`（顶栏仍可见 RAG Coder 入口，access≠可见性成立）；翻成 member/approved → `/admin` 弹回首页、审核入口消失、`/rag` 可进；验后恢复 admin。不需要第二个 GitHub 账号：jwt 回调每次刷新回库取状态，改库即改会话
- [x] 5.3 `openspec validate --strict` 通过
