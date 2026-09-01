# project-management — 删除权限（M8）

## MODIFIED Requirements

### Requirement: 项目删除
`DELETE /projects/{id}`（级联删除 Postgres 记录、Neo4j 子图与本地仓库副本）SHALL 仅 admin 可执行；member 调用返回 403，前端对 member 不显示删除入口。项目的创建、索引、查询保持全员可用（登录态下）。

#### Scenario: member 不能删项目
- **WHEN** member 登录态调用 DELETE /projects/{id}
- **THEN** 403，数据无变化
