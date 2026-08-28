## ADDED Requirements

### Requirement: 容量状态查询
系统 SHALL 提供容量状态接口，返回项目槽位用量（已用/上限）、服务器磁盘剩余与总量、是否接受新项目录入的判定及不接受时的原因；登录用户均可查询。

#### Scenario: 容量状态可见
- **WHEN** 登录用户请求容量状态
- **THEN** 返回 projects_used/projects_limit/disk_free_gb/disk_total_gb/accepting 字段，accepting=false 时附带人类可读的 reason

### Requirement: 录入容量双护栏
录入新项目 SHALL 在创建记录前校验双护栏：项目数达到上限或磁盘剩余低于阈值时 SHALL 拒绝（409）并返回原因；上限与阈值 SHALL 可经环境变量配置。重新索引已有项目与删除项目 SHALL NOT 受容量限制；删除项目后槽位即时释放。

#### Scenario: 槽位满拒绝新建
- **WHEN** 项目数已达上限，用户录入新仓库
- **THEN** 返回 409 与"项目槽位已满"类原因，不产生新项目记录

#### Scenario: 磁盘不足拒绝新建
- **WHEN** 磁盘剩余低于阈值，用户录入新仓库
- **THEN** 返回 409 与"磁盘空间不足"类原因

#### Scenario: 重索引不受限
- **WHEN** 容量已满，用户对已有项目触发重新索引
- **THEN** 正常受理，不因容量拒绝

#### Scenario: 删除释放槽位
- **WHEN** 满额状态下删除一个项目后再录入新仓库
- **THEN** 录入成功
