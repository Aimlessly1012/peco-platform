# artifact-storage — 存储层硬化与可验证性（M17）

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: 源码 bundle 主存储
MinIO SHALL 以 git bundle（含完整历史与全部分支）作为每个项目源码的唯一持久存储，key 固定为项目级（覆盖写）；bundle 上传失败 SHALL 降级为 warning 不影响索引任务成败。再次索引已有 bundle 的项目时 SHALL 优先从 bundle 恢复工作区（增量拉取远端差量），恢复来源 SHALL 记入任务 stats（`code_source`）可供断言与巡检。

#### Scenario: 索引成功后 bundle 更新
- **WHEN** 索引任务成功完成
- **THEN** MinIO 中该项目的 bundle 反映最新 commit，可被 git clone 直接恢复出完整仓库

#### Scenario: 二次索引从 bundle 恢复
- **WHEN** 项目已有 bundle，再次触发索引
- **THEN** 工作区由 bundle 恢复而非远端全量 clone，任务 stats 的 `code_source` 为 bundle 来源标记，增量索引结果正确
