## ADDED Requirements

### Requirement: 注册表是项目清单的唯一事实源

`lib/projects.ts` MUST 以类型化数组声明全部项目（`key` / `label` / `route` / `access` /
`backend`，及可选 `showcase` 作品资料）。TopBar 导航与首页作品区 MUST 从注册表渲染，
MUST NOT 各自硬编码项目清单。首页作品区只渲染具备 `showcase` 的条目——无 `showcase` 的
内部工具（如审核台）仅按 access 规则出现在导航，MUST NOT 进入作品区。

#### Scenario: 加一行即上导航

- **WHEN** 注册表新增一个带 `showcase` 资料的项目条目
- **THEN** 不改任何组件代码，TopBar 与首页作品区即出现该项目入口

#### Scenario: 内部工具不进作品区

- **WHEN** 注册表条目未提供 `showcase`（如审核台）
- **THEN** 该条目按 access 规则出现在导航，首页作品区不出现它

#### Scenario: 删一行即下架

- **WHEN** 注册表移除一个项目条目
- **THEN** 导航与首页不再出现该项目，无残留死链

### Requirement: 访问级别声明一次、双层执行

项目的访问级别 MUST 在注册表以 `access: "public" | "approved" | "admin"` 声明。
middleware MUST 按注册表执行：`approved` 要求已批准且未禁用，`admin` 追加管理员角色。
middleware 是体验层，项目后端 MUST 自行验证 JWS——注册表声明 MUST NOT 被当作唯一防线。

`access` 控制的是**进入**而非**可见性**：`approved` 项目的导航与首页入口 MUST 对所有
登录用户可见——待审用户点击后由 middleware 送往 `/pending`，「看得见但进不去、并被告知
原因」优于「入口凭空消失」。仅 `admin` 项目 MUST 对非管理员隐藏入口（延续既有行为）。

#### Scenario: 待审用户被挡在 approved 项目外

- **WHEN** `status=pending` 的用户访问一个 `access: "approved"` 的项目路由
- **THEN** 被重定向到 `/pending`，未见到页面内容

#### Scenario: 入口可见但受控

- **WHEN** `status=pending` 的用户查看 TopBar 与首页
- **THEN** `approved` 项目的入口正常可见，点击后落在 `/pending`；`admin` 项目的入口不出现

#### Scenario: 非管理员被挡在 admin 项目外

- **WHEN** `role=member` 的用户访问一个 `access: "admin"` 的项目路由
- **THEN** 被重定向离开，未见到页面内容

### Requirement: matcher 覆盖受机器守卫

守卫脚本 MUST 校验 matcher 对注册表的覆盖：每个 `access ≠ public` 的项目，其裸路径与
`:path*` 两条 MUST 同时存在于 matcher，缺失时 MUST 非零退出并指明缺哪个项目的哪一条，
且守卫 MUST 接入 CI。（背景：Next 的 `config.matcher` 是静态字面量、无法由注册表生成，
受保护项目的条目只能手写——这正是守卫存在的原因。）

#### Scenario: 漏写 matcher 被当场拦下

- **WHEN** 注册表新增一个 `access: "approved"` 的项目而 middleware matcher 未同步
- **THEN** 守卫脚本非零退出，输出该项目缺失的具体条目（裸路径、`:path*` 或两者）

#### Scenario: 裸路径陷阱被单独识别

- **WHEN** matcher 只写了某受保护项目的 `"/x/:path*"` 而缺 `"/x"`
- **THEN** 守卫脚本非零退出，明确指出缺的是裸路径条目

#### Scenario: 全覆盖时安静通过

- **WHEN** 注册表与 matcher 一致
- **THEN** 守卫脚本以零退出码结束

### Requirement: 新增项目仅新增文件加三处受守卫的登记

nginx 主配置 MUST 通过 `include projects/*.conf` 装配各项目的转发规则；该目录 MUST NOT
挂载于 `/etc/nginx/conf.d/` 之下——nginx 默认把 conf.d 中的文件当 **http 块顶层配置**加载，
而这些是 location 片段，容器会直接起不来；SHALL 挂载为独立路径（如 `/etc/nginx/projects/`）。
编排 MUST 按项目一个 compose 文件；Compose 的 `include` 不支持通配符（实测），带后端的
项目 MUST 在伞文件的 include 列表登记一行——此为第三处登记。守卫脚本 MUST 校验：注册表中
`backend: true` 的项目，其 `deploy/compose/<key>.yml` MUST 存在且 MUST 被伞文件 include，
缺失即非零退出。新增一个项目 MUST NOT 要求编辑注册表、matcher 与伞文件 include 之外的
任何既有文件。

#### Scenario: 走一遍新增流程

- **WHEN** 按接入清单新增一个假想项目（页面目录、可选后端目录、nginx conf、compose yml、
  注册表一行、matcher 两行、伞文件 include 一行）
- **THEN** 除注册表、middleware 与伞文件外，git diff 中不出现对既有文件的修改

#### Scenario: 漏登 compose include 会响

- **WHEN** 注册表新增 `backend: true` 的项目，`deploy/compose/<key>.yml` 缺失或未被伞文件 include
- **THEN** 守卫脚本非零退出，指明缺的是 compose 文件还是 include 行
