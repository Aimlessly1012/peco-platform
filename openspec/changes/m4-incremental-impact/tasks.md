# Tasks: M4 增量重索引 / 影响面多跳 / 可观测性（B=后端 / V=PM 验收；本里程碑无前端结构改动）

## 1. 可观测性与健壮性（先做——立即改善大仓库体验）

- [ ] B1 子进度回调：summarizer/embedder 接受 on_progress(done,total)，pipeline 节流写库（每 5% 或 ≥2s），summarize 25-55、embed 55-85 线性映射；stats 加 summarize_done/total、embed_done/total
- [ ] B2 显式超时：LLM_TIMEOUT_SECONDS（默认 60）/ EMBEDDING_TIMEOUT_SECONDS（默认 30）注入 AsyncOpenAI 构造，超时进入既有退避降级；.env.example 更新
- [ ] B3 File 节点补存 imports 属性（graph_writer），为增量读回做准备

## 2. 增量重索引

- [ ] B4 git diff 模块：diff_changed_files(repo_dir, old_sha, new_sha) → {added, modified, deleted}（R 拆 D+A）；单测
- [ ] B5 图局部操作：delete_files_subgraph(pid, paths)、load_file_metadata(pid)（读回未变文件 path/hash/summary/imports，缺 imports 现场重提取）、结构边全量重连（先删四类边）
- [ ] B6 pipeline auto 分支：mode 参数贯通（API ?mode= → start_index_job → kind 记录实际路径）；auto 判定与 fallback_full_reason；无变更秒返（no_changes）；变更文件走既有解析/摘要/嵌入路径，未变更节点不动；last_indexed_commit 仅成功后更新
- [ ] B7 增量正确性集成测试（图等价基准，设计 D2）：fixture 全量快照 → 改/增/删文件 → 增量 vs 全量图等价断言 + 未变更文件 embedding 保留断言 + 无变更秒返断言

## 3. 影响面多跳

- [ ] B8 检索服务层 impact_of(project_id, file_or_symbol, max_depth≤3)：反向 IMPORTS 变长路径 + CALLS_API 前端调用方 + 模块聚合，LIMIT 200，输出 direct/transitive(depth,path)/frontend_callers/modules_affected；fixture 集成测试（多层 import 链断言分层正确）
- [ ] B9 classify 三分类（global|local|impact，少样本扩充，失败仍回退 local）+ retrieve impact 策略（向量定位目标 → impact_of → 影响树格式化并入资料）；目标定位失败降级 local
- [ ] B10 MCP impact_analysis 升级：max_depth 参数（默认 2）、分层输出对齐 B8；工具描述更新

## 4. 前端路由探测器扩展（真实反馈：umi 项目全量 fallback）

- [ ] B13 umi 探测器：识别标志（package.json 依赖 umi/@umijs/max 或存在 .umirc.ts）→ 约定式路由（src/pages 文件路由，含 [id]/$id 动态段、_layout 排除）+ 配置式路由（.umirc.ts / config/routes.ts / config/config.ts 的 routes 数组，component '@/pages/..' 解析为入口文件）→ 按路由首段分组产出 kind=page 模块；fixture 单测（约定式与配置式各一）
- [ ] B14 降级两级化 + 巨模块细分：探测失败时优先页面目录感知分组（src/pages、src/views、app 二级子目录），否则顶层目录；任一模块 >200 文件自动按子目录细分（递归一层）；单测覆盖 src 巨目录场景

## 5. MCP 鉴权与收尾

- [ ] B11 MCP_AUTH_TOKEN：ASGI 中间件拦 /mcp 校验 Bearer（空则跳过），401 结构化错误；/mcp-guide 页在鉴权开启时展示带 header 命令（读后端新增的 GET /mcp-info 或构建时环境变量，取实现简单者）
- [ ] B12 README 更新（增量语义、mode 参数、超时与鉴权配置、支持的路由框架清单）

## 6. V 组（PM 验收）

- [ ] V1 全量测试绿 + 容器重建
- [ ] V2 真实验收：ad.anynovel.app（umi 大仓库）——mode=full 重索引后 router_fallback=false 且产出按路由分组的 page 模块（不再有 1133 文件巨模块）；随后改动仓库触发 auto 增量观察秒级/局部行为与连续子进度；聊天问"改 XX 文件影响哪些地方"得到分层回答；MCP impact_analysis(max_depth=3) 实测
- [ ] V3 提交与归档
