## Context

增量索引依赖本地 .git 的 git diff（build_index_plan 显式检查，缺失自动 fallback 全量且有缓存兜底）；无变化秒回靠本地 git pull 后 SHA 对比。M13+ 的 tarball 归档不含 .git。探讨对比过三形态（即用即弃全量 / 本地缓存 / git bundle），用户选定 bundle——唯一既满足「本地不持久」又保全增量与秒回的方案，且公网成本反而低于现状外的其他方案。

## Goals / Non-Goals

**Goals:** MinIO 成为源码唯一持久层；增量 diff 与无变化秒回语义保全；bundle 缺失/损坏时的完整容错链；多机 worker 就绪。
**Non-Goals:** 不做增量 bundle（全量 bundle 简单可靠，体积≈.git 可接受）；不为聊天引用回读源文件（chunk 文本在 Neo4j，不依赖工作区）。

## Decisions

- **D1 秒回前移到 ls-remote**：任务开头 `git ls-remote origin <branch>` 一次网络请求拿远端 HEAD，与 last_indexed_commit 相同即秒回——比现状（先 pull 再比）还省，且不需要任何本地状态。
- **D2 bundle 恢复流程**：拉 bundle → `git clone <bundle> workdir -b <branch>` → `git remote set-url origin <真实URL>` → `git fetch --tags origin <branch>` → checkout 远端最新。fetch 只传 bundle 之后的新对象。
- **D3 归档时机与保留**：六阶段成功后 `git bundle create --all` 推 MinIO，key `repo-bundles/{project_id}.bundle`（固定 key 覆盖写，不留历史——bundle 自含全史）；上传失败仅 warning（与既有归档纪律一致），下次任务走 clone 远端容错链。
- **D4 工作区生命周期**：tempfile.mkdtemp 每任务独立目录，finally 清理；repos_dir 配置保留作为临时根（便于磁盘监控），不再有跨任务状态。
- **D5 tarball 退役**：archive_repo_tarball 及保留策略删除；repo-archives/ 桶内历史对象一次性清理或保留自然过期（验收时定）。
- **D6 容错矩阵**：bundle 拉取失败/clone bundle 失败 → clone 远端；fetch 失败（token 失效/force push）→ clone 远端；diff 断链 → 既有 fallback 全量。任何一环失败都不该让任务失败在"取码"这一步之外。

## Risks / Trade-offs

- [每任务 bundle 往返 ~.git 体积] → 内网 MinIO 秒级；远超收益线的巨型仓库（GB 级 .git）本就不是本系统目标场景
- [固定 key 覆盖写丢历史 bundle] → bundle 自含全史，"历史版本源码"用 git 历史即可回溯；接受
- [并发同项目任务写 bundle 竞争] → worker concurrency=1 串行，天然无竞争
- [容器 tmp 空间] → 工作区峰值≈工作树+.git，任务尾即清；worker mem_limit 不变

## Migration Plan

实现+测试 → 部署 → 触发既有项目索引验证 bundle 生成与恢复（含手动删本地 repos 后再索引的实测）→ 验收后移除 compose repos 卷挂载与 tarball 桶内旧对象。回滚 = 回退镜像（repos 目录数据仍在，天然可回退）。

## Open Questions

- compose 移除 repos 卷的时机：与本 change 一起，还是观察一周后单独做（保守）
