# 对象存储产物

MinIO 三类产物：源码 bundle 主存储（M16）、解析产物快照、报告导出件。均带降级语义。（M13 的 tarball 归档已由 bundle 取代；解析快照归档保留——m16 delta 的 REMOVED 按代码现实裁决为仅 tarball 场景退役。）

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
MinIO SHALL 以 git bundle（含完整历史与全部分支）作为每个项目源码的唯一持久存储，key 固定为项目级（覆盖写）；bundle 上传失败 SHALL 降级为 warning 不影响索引任务成败。

#### Scenario: 索引成功后 bundle 更新
- **WHEN** 索引任务成功完成
- **THEN** MinIO 中该项目的 bundle 反映最新 commit，可被 git clone 直接恢复出完整仓库
