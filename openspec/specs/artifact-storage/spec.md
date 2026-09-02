# 对象存储产物

## Purpose
MinIO 三类产物：源码 bundle 主存储（M16）、解析产物快照、报告导出件。均带降级语义。（M13 的 tarball 归档已由 bundle 取代；解析快照归档保留——m16 delta 的 REMOVED 按代码现实裁决为仅 tarball 场景退役。）

## Requirements

### Requirement: 对象存储与桶初始化
系统 SHALL 提供 MinIO 对象存储；应用启动时 SHALL 确保所需桶存在（不存在则创建）；访问凭据 SHALL 仅来自环境变量，SHALL NOT 出现在代码或 .env.example 实值中。

#### Scenario: 首次启动自动建桶
- **WHEN** 后端在全新 MinIO 实例上启动
- **THEN** 所需桶被自动创建，后续读写正常

### Requirement: 报告导出件存储
理解报告的导出件 SHALL 上传至 MinIO 并可按项目检索下载。

#### Scenario: 报告导出可下载
- **WHEN** 用户导出某项目的理解报告
- **THEN** 导出件写入 MinIO，用户获得可下载的文件

### Requirement: 索引产物归档非关键路径
索引完成后 SHALL 将解析产物快照归档至 MinIO；归档失败 SHALL 降级为 warning 记入 stats，SHALL NOT 导致索引任务失败。

#### Scenario: MinIO 不可用不阻塞索引
- **WHEN** 索引成功完成但 MinIO 不可达
- **THEN** 任务仍为 succeeded，stats 含归档失败 warning

### Requirement: 源码 bundle 主存储
MinIO SHALL 以 git bundle（含完整历史与全部分支）作为每个项目源码的唯一持久存储，key 固定为项目级（覆盖写）；bundle 上传失败 SHALL 降级为 warning 不影响索引任务成败。再次索引已有 bundle 的项目时 SHALL 优先从 bundle 恢复工作区（增量拉取远端差量），恢复来源 SHALL 记入任务 stats（`code_source`）可供断言与巡检。

#### Scenario: 索引成功后 bundle 更新
- **WHEN** 索引任务成功完成
- **THEN** MinIO 中该项目的 bundle 反映最新 commit，可被 git clone 直接恢复出完整仓库

#### Scenario: 二次索引从 bundle 恢复
- **WHEN** 项目已有 bundle，再次触发索引
- **THEN** 工作区由 bundle 恢复而非远端全量 clone，任务 stats 的 `code_source` 为 bundle 来源标记，增量索引结果正确

### Requirement: bundle 上传前自校验
`export_bundle` 产出 bundle 后 SHALL 先执行 `git bundle verify`，校验通过才上传覆盖远端；校验失败 SHALL 不上传、保留远端既有 bundle，并以 warning 记入任务 stats。坏包 SHALL NOT 覆盖好包。

#### Scenario: 坏包不覆盖好包
- **WHEN** bundle 产出过程受损（如磁盘写入异常）导致 verify 失败
- **THEN** 上传被跳过，MinIO 中保留上一个可用 bundle，任务 stats 含校验失败 warning，任务成败不受影响

### Requirement: 对象存储客户端超时
MinIO 客户端 SHALL 配置显式的连接与读超时（秒级，可配置有默认值）；MinIO 服务挂起（可连接但不响应）时，下载与上传 SHALL 在超时上限内返回并走既有降级路径（下载失败回退 clone、上传失败记 warning），SHALL NOT 使索引任务无限期阻塞。

#### Scenario: MinIO 挂起不阻塞索引
- **WHEN** MinIO 端口可连接但请求无响应
- **THEN** bundle 下载在超时上限内放弃并回退全量 clone，索引任务正常推进
