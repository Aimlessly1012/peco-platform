## Why

用户的目标形态：本地盘不再是源码的持久层，「代码都存 MinIO」。现状 data/repos 是常驻工作副本；M13+ 的 tarball 归档只是快照（无 .git，救不了增量索引）。用 git bundle（官方单文件仓库格式，含完整历史）作为 MinIO 里的源码主存储，本地盘降级为任务运行时的临时工作区——增量 diff、无变化秒回全部保留，且天然多机就绪。

## What Changes

- 归档格式从 tarball 换 **git bundle**（`git bundle create --all`，每项目留最新 1 份——bundle 自含全部历史，不需按 commit 攒多份）
- 索引任务工作区生命周期重构：任务开始 `git ls-remote` 查远端 HEAD（与基准相同→秒回，bundle 都不拉）→ MinIO 拉 bundle → clone from bundle → set-url 真实远端 → fetch 增量 → 六阶段照常（.git 在手，增量 diff 保全）→ `git bundle create` 推回 MinIO → 删临时工作区
- 容错链：bundle 缺失/损坏 → 直接 clone 远端（等于首次索引）；force push/diff 断链 → 既有 GitDiffError fallback 全量 + 重建 bundle
- **本地持久占用归零**：data/repos 从常驻存储变为临时目录，任务尾清理
- tarball 归档退役（bundle 是其信息超集；需要给人用的 tarball 时可从 bundle 导出）

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `artifact-storage`: 源码归档从 tarball 快照升级为 git bundle 主存储；MinIO 成为源码唯一持久层
- `indexing-pipeline`: 仓库副本语义从「本地常驻工作副本」变为「MinIO bundle + 任务级临时工作区」；无变化检测改为 ls-remote 先行

## Impact

- 后端：git_ops（bundle 恢复/ls-remote/bundle 归档三个函数）、pipeline 头尾（工作区准备与清理）、storage 层复用既有对象操作；tarball 相关代码退役
- 部署：compose 的 repos 卷可在验收后移除（临时目录用容器内 tmp）
- 网络画像变化：公网 GitHub 流量大降（只 fetch 增量），内网 MinIO 每任务 bundle 往返（~.git 体积）
