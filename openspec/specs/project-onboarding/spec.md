# project-onboarding Specification

## Purpose
TBD - created by archiving change platform-project-slots. Update Purpose after archive.
## Requirements
### Requirement: 登录直走一套

项目 MUST NOT 自建登录、注册或会话体系；`/login`（平台 GitHub OAuth）MUST 是全平台唯一
登录入口。项目后端 MUST 以平台共享密钥验证 JWS 会话 cookie（HS256；claim：`githubId` /
`role` / `status`），并 MUST 以此作为唯一身份来源。

#### Scenario: 无凭据请求被后端拒绝

- **WHEN** 不带会话 cookie 请求某项目后端的受保护接口
- **THEN** 后端返回 401，未执行业务逻辑

#### Scenario: 平台 cookie 全平台通行

- **WHEN** 用户在 `/login` 完成一次登录后访问任意项目的页面与接口
- **THEN** 同一 cookie 在各项目后端验签通过，无需二次登录

#### Scenario: 契约参数即验签的全部所需

- **WHEN** 一个新语言编写的后端按 spec 所列参数（算法、claim 名、共享密钥）实现验签
- **THEN** 不阅读平台源码即可完成接入并通过联调

### Requirement: 接入清单可执行

平台 MUST 维护一份按序可执行的项目接入清单，覆盖：页面目录、后端目录（纯前端项目可省）、
nginx 转发文件、compose 文件、注册表登记、matcher 登记、JWS 验签接入。清单 MUST 与守卫
脚本的校验范围一致——清单要求登记的地方，守卫 MUST 能发现漏登。

#### Scenario: 照清单走通

- **WHEN** 按清单逐步新增一个项目
- **THEN** 完成后守卫脚本、lint、build 全绿，项目入口出现在导航与首页

#### Scenario: 跳步会被守卫抓住

- **WHEN** 执行清单时跳过 matcher 登记一步
- **THEN** 守卫脚本非零退出，指明缺失项

