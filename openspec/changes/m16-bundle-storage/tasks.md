## 1. git_ops 三件套

- [ ] 1.1 ls_remote_head(git_url, branch, token)：一次网络请求取远端 HEAD SHA
- [ ] 1.2 restore_workdir：MinIO 拉 bundle → clone → set-url → fetch → checkout 最新；bundle 缺失/损坏/fetch 失败逐级 fallback 到 clone 远端（容错矩阵 D6）
- [ ] 1.3 export_bundle：git bundle create --all → 上传 MinIO 固定 key，失败仅 warning

## 2. pipeline 接线

- [ ] 2.1 任务头：ls-remote 秒回判定前移（无变化不建工作区）；工作区 mkdtemp + finally 清理
- [ ] 2.2 clone 阶段换 restore_workdir；六阶段与增量 plan 逻辑不动（.git 在手 diff 照常）
- [ ] 2.3 成功尾部 export_bundle；tarball 归档代码与保留策略退役（含测试）

## 3. 测试

- [ ] 3.1 bundle 往返：真实小 git 仓库 → bundle → 恢复 → fetch 新 commit → diff 正确
- [ ] 3.2 容错矩阵：bundle 缺失/损坏/fetch 失败 → clone 远端成功；上传失败仅 warning
- [ ] 3.3 秒回：ls-remote 相同 SHA → 不触存储不建工作区；全量回归全绿

## 4. 部署与验收

- [ ] 4.1 部署（build backend worker 都点名）；触发真实索引验证 bundle 生成
- [ ] 4.2 破坏性验收：服务器删除本地 repos 后触发索引，经 bundle 恢复成功且增量语义保全
- [ ] 4.3 清理 repo-archives 旧 tarball；观察一周后单独移除 compose repos 卷（Open Question 保守解）
