# M10: 聊天首答提速（模型分工 + 上下文预算）

> **归档说明（M17，2026-08-31）**：本 change 原误置于 `backend/openspec/changes/`，
> 2026-08-28 的 M6–M16 批量归档因此漏掉了它。其 delta 所用的 requirement 标题与现行主
> spec 结构不符，未做机械 sync——两条需求（上下文预算裁剪、生成与离线模型分流）已由
> M17（m17-test-baseline）的 code-chat delta 按现行结构补录进主 spec。本目录仅存档原文。

## Why

M9 上线后测得公网首 token 61.9s、完整回答 65.5s，用户体感"卡住"。分阶段量化后定位：
- understand（合并后的理解+分类）4.9s
- retrieve（检索 + rerank）1.4s
- **generate 首字 54s** ← 瓶颈

进一步实验排除了链路问题：同一 10K 字符上下文直接调用只要 8.8-14.4s，波动 3 倍，
说明推理型模型（DeepSeek-V4-Flash）的 prefill + reasoning 成本叠加服务商负载才是主因。

## What Changes

| # | 变更 | 依据（服务器实测） |
|---|------|------|
| 1 | 问答链路换代码专用非推理模型 `Qwen3-Coder-30B-A3B-Instruct` | 同一上下文首字 0.9s vs 13.1s，`[n]` 引用 8 处 vs 3 处；分类准确率 5/5 持平，追问改写正确 |
| 2 | `GENERATE_MODEL` 配置（空则回落 `CHAT_MODEL`） | 生成与理解可分别选型，互不影响 |
| 3 | 上下文字符预算 `CONTEXT_CHAR_BUDGET`（默认 9000）+ `context_min_items` 底线 | 原本 16 条 ≈ 7600 字符全量入 prompt |
| 4 | 报告 LLM 补 `summary_model` 回落 | 原先硬读 `chat_model`，换模型会连报告件质量一起换掉（summarizer 有回落，它没有） |
| 5 | rerank 超时 5s → 15s | 日志实测「rerank 超时（5.0s），保持原有排序」——M7 配的精排一直静默降级 |

## 结果

首 token 61.9s → **6.0-6.5s**，完整回答 65.5s → **12.3s**，引用资料 15-17 条且 `[n]` 编号对齐。
模型分工：`chat_model` 在线问答（快优先）／ `summary_model` 索引摘要与报告件（质量优先）。

## 权衡

非推理模型偶尔不如推理型谨慎（实测把"用户主动查询触发"表述为"系统定期检查"），
但引用标注更多、可自行核实。删 `GENERATE_MODEL` 并还原 `CHAT_MODEL` 即完全回退。

## Capabilities

- `code-chat`（MODIFIED）：模型分工与上下文预算
