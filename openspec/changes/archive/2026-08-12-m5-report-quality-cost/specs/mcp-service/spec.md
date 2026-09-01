# mcp-service — 报告四件措辞对齐（M5）

## MODIFIED Requirements

### Requirement: 七个检索工具
MCP SHALL 暴露以下工具，全部复用既有检索服务层与图数据，输出精简 JSON 且代码定位一律为 `文件路径 + 行号区间`：list_projects、get_project_overview、get_module_map、search_code（top_k 上限 20，代码片段截断 80 行）、get_file_summary（含 imports 与 imported_by）、impact_analysis（多跳影响：反向 IMPORTS 传播，max_depth 参数默认 2、上限 3，结果含 direct/transitive（带深度与路径）/frontend_callers/modules_affected 分层，结果上限 200）、get_project_understanding（报告四件：文档、顶层导图、数据流图、时序图，含 depth 标记；fast 报告的文档与时序图为空）。project 参数 SHALL 接受项目名或 uuid，重名取最新创建者且返回中携带 resolved_project_id。

#### Scenario: agent 检索代码
- **WHEN** agent 调用 search_code(project, "订单创建逻辑", top_k=5)
- **THEN** 返回 ≤5 条结果，各含 file_path、行号区间、symbol 与代码片段，且仅属于该项目

#### Scenario: 影响面多跳分层
- **WHEN** agent 对被多层依赖的文件调用 impact_analysis(max_depth=3)
- **THEN** 返回 direct 与 transitive 分层清单（transitive 项含 depth 与传播路径）、前端调用方及波及模块聚合
