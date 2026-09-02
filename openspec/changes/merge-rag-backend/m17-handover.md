# m17-test-baseline 迁移交接（任务 1.2）

**状态采集**：2026-09-01 · RAG_coder@`ceddadf` · 进度 **23/25**

m17 不是「做完了搬」，而是**随迁继续**：并入后它进入本仓库根 `openspec/changes/`，
剩余两项在新位置完成。这份说明记录的是迁移那一刻它的状态，供并入后接续时对照。

## 剩余两项

两项是同一件事的两半，都卡在「真实模型评测尚未跑过一次」：

- **3.5** 真实模型评测脚本 `backend/scripts/eval_retrieval.py`（真 embedding + 可选 rerank，
  手动触发），跑通一次并把首个质量基线数（含日期 / 模型 / 配置指纹）记入 `docs/`
- **6.3** 真实档基线数已入 docs 且含配置指纹；`openspec status` 全勾后归档

3.5 未完成 6.3 就无法勾——后者验收的正是前者的产出物。

**为什么一直没做**：它需要真 embedding 调用（默认走本地 Ollama bge-m3，或换 DashScope），
不是纯断言，跑一次有成本也有耗时，CI 里是手动触发口而非门禁。离线评测那一层（快照断言）
已完成并进了 CI 双 job。

## 并入后路径变化

接续时这些引用要跟着改，脚本自身的相对路径假设也要重验：

| 迁移前 | 迁移后 |
|---|---|
| `backend/scripts/eval_retrieval.py` | `services/rag/scripts/eval_retrieval.py` |
| `docs/`（基线数写入目标） | `services/rag/docs/` |
| `openspec/changes/m17-test-baseline/` | 根 `openspec/changes/m17-test-baseline/` |
| CI job 工作目录 `backend/` | `services/rag/`（含 `paths:` 过滤与缓存路径） |

CI 的迁移属于本 change 的 2.4，不在 m17 范围内；但 3.5 的手动触发口是 CI 里的 job，
2.4 改完后接续 3.5 前应先确认那个入口仍可触发。

## 迁移时的未提交改动

冻结旧仓库前（任务 1.4）工作区有两处，**都不是 m17 的工作成果**：

- `backend/app/api/projects.py`：纯格式化（import 重排 + black 风格换行），无逻辑变更。
  像是格式化工具扫过留下的，与 m15 里那 108 行 `chat/page.tsx` 同类
- `.claude/launch.json`：未跟踪的本地工具配置，内容含本机绝对路径
  （`/Users/peco/Documents/Peco/...`），**不应入库**

**1.4 已执行**（用户裁定）：`projects.py` 的格式化改动已 `git checkout` 丢弃——18 行全是
import 重排、三元表达式换行与注释前空格，逐行确认零逻辑变更，不值得让冻结中的仓库
多一个 commit。`.claude/launch.json` 保留在工作区不入库。

m17 本身没有未提交的进度——23 项的勾选状态全在 `ceddadf` 里。

## 冻结点

**RAG_coder 冻结于 `ceddadf`**，`main` 与 `origin/main` 同步，无未推送提交，
已跟踪文件零改动（仅剩未跟踪的 `.claude/launch.json`）。

subtree 并入取的就是这个点，并入 commit 的 message 需写明来源仓库与源 HEAD（任务 2.2）。
自此旧仓库不再接受新提交，RAG 侧开发在并入后的 `services/rag/` 继续。
