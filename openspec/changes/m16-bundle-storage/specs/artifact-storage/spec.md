## ADDED Requirements

### Requirement: 源码 bundle 主存储
MinIO SHALL 以 git bundle（含完整历史与全部分支）作为每个项目源码的唯一持久存储，key 固定为项目级（覆盖写）；bundle 上传失败 SHALL 降级为 warning 不影响索引任务成败。

#### Scenario: 索引成功后 bundle 更新
- **WHEN** 索引任务成功完成
- **THEN** MinIO 中该项目的 bundle 反映最新 commit，可被 git clone 直接恢复出完整仓库

## REMOVED Requirements

### Requirement: 索引产物归档非关键路径
**Reason**: 源码归档从 tarball 快照升级为 git bundle 主存储（本 change 的 ADDED 需求），tarball 归档退役；解析产物 JSON 快照的归档行为并入 bundle 时代不变，但 tarball 相关场景不再适用。
**Migration**: repo-archives/ 桶内既有 tarball 对象一次性清理；需要人类可读快照时从 bundle 克隆后 git archive 导出。
