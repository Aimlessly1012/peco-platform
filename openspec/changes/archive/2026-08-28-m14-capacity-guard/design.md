## Context

3.6G 单机跑 Postgres/Neo4j/backend/worker/RabbitMQ/MinIO/platform 全套。实测（2026-08-26）：磁盘 59G 剩 41G 宽裕；Neo4j 2 个项目占 1.1G 磁盘、640M 常驻内存——**项目数才是先崩的约束**，磁盘阈值只是兜底。用户决策：双护栏、上限 8、只拦新建。

## Goals / Non-Goals

**Goals:** 容量可见（槽位+磁盘）；超限时新建被明确拒绝（有原因文案）；阈值可调。
**Non-Goals:** 不做按项目大小的精细配额；不拦重索引与删除；不做 Neo4j 内存实时监控（用项目数作代理指标）。

## Decisions

- **D1 双护栏口径**：`projects_used < PROJECT_LIMIT(8)` 且 `disk_free_gb > DISK_MIN_FREE_GB(5)` 才接受新建。项目数是主约束（对应内存瓶颈），磁盘是兜底。
- **D2 磁盘检测**：`shutil.disk_usage("/")`——backend 容器的 overlay fs 落在宿主盘上，statvfs 数字与宿主一致，不必挂 /proc。
- **D3 接口放 meta router**（`GET /meta/capacity`，已有 require_user 依赖）：返回 `{projects_used, projects_limit, disk_free_gb, disk_total_gb, accepting, reason}`。reason 只在 accepting=false 时非空，前端直接展示不再拼文案。
- **D4 拦截点在创建项目 API**：校验在建记录之前；拒绝用 409（与"已有 running 任务"一致的冲突语义）。不加锁——单机低并发下 count 竞态最多超额 1 个，可接受。
- **D5 前端容量条**：项目列表页顶部终端风一行（`SLOTS n/8 · DISK 41G free`），accepting=false 时新建按钮禁用 + 显示 reason。数据来自 capacity 接口，与项目列表一并拉取。

## Risks / Trade-offs

- [并发创建可能超额 1 个] → 可接受（member 数量个位数）；如需严格可后补 DB 约束
- [磁盘阈值在容器视角与宿主偏差] → overlay 同盘，偏差可忽略；验收时对照 df 实测
- [槽位上限拍脑袋] → env 可调，上线后按 Neo4j 内存实测回调

## Migration Plan

后端实现+测试 → 前端容量条 → 部署（.env 加两个配置）→ 线上验证：8 槽位显示正确、模拟满额拒绝（临时把 LIMIT 调 2 验证 409 与前端禁用态）→ 恢复配置。

## Open Questions

（无）
