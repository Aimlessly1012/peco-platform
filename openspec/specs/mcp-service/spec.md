# mcp-service Specification

## Purpose
MCP 服务能力：在后端同进程以 streamable-http 传输挂载 MCP 端点，向 Claude Code 等 agent 暴露七个项目检索工具（项目清单/项目总览/模块地图/代码搜索/文件摘要/影响面分析/项目理解报告），含结构化错误契约、项目隔离与前端接入说明页。

## Requirements

### Requirement: MCP 端点挂载
系统 SHALL 以官方 Python SDK（FastMCP）的 streamable-http 传输在后端同进程挂载 MCP 端点 `/mcp`；Claude Code 通过 `claude mcp add --transport http rag-coder http://localhost:8001/mcp` 接入。端点生命周期 MUST 与 FastAPI 应用一致（随应用启停）。

#### Scenario: MCP 握手可用
- **WHEN** MCP 客户端对 /mcp 发起 initialize
- **THEN** 返回服务器信息与 7 个工具的定义清单

### Requirement: 七个检索工具
MCP SHALL 暴露以下工具，全部复用既有检索服务层与图数据，输出精简 JSON 且代码定位一律为 `文件路径 + 行号区间`：list_projects、get_project_overview、get_module_map、search_code（top_k 上限 20，代码片段截断 80 行）、get_file_summary（含 imports 与 imported_by）、impact_analysis（多跳影响：反向 IMPORTS 传播，max_depth 参数默认 2、上限 3，结果含 direct/transitive（带深度与路径）/frontend_callers/modules_affected 分层，结果上限 200）、get_project_understanding（报告三件套）。project 参数 SHALL 接受项目名或 uuid，重名取最新创建者且返回中携带 resolved_project_id。

#### Scenario: agent 检索代码
- **WHEN** agent 调用 search_code(project, "订单创建逻辑", top_k=5)
- **THEN** 返回 ≤5 条结果，各含 file_path、行号区间、symbol 与代码片段，且仅属于该项目

#### Scenario: 影响面多跳分层
- **WHEN** agent 对被多层依赖的文件调用 impact_analysis(max_depth=3)
- **THEN** 返回 direct 与 transitive 分层清单（transitive 项含 depth 与传播路径）、前端调用方及波及模块聚合

### Requirement: MCP 错误与隔离契约
工具在项目不存在、未就绪（非 ready）或参数非法时 MUST 返回结构化错误文本（含状态与建议），不得抛出未处理异常导致连接中断；所有查询 MUST 按解析后的 project_id 过滤。

#### Scenario: 项目未就绪
- **WHEN** agent 对 indexing 状态的项目调用 search_code
- **THEN** 返回"项目索引未完成（indexing）"类错误文本，连接保持可用

### Requirement: MCP 接入说明页
前端 SHALL 提供 MCP 接入说明页：展示 MCP URL、Claude Code 添加命令（可复制）、7 个工具的名称与一句话用途。

#### Scenario: 复制接入命令
- **WHEN** 用户打开 MCP 说明页
- **THEN** 可一键复制 `claude mcp add` 完整命令

### Requirement: MCP 可选鉴权
系统 SHALL 支持 MCP_AUTH_TOKEN 环境变量：非空时 /mcp 全部请求 MUST 携带匹配的 `Authorization: Bearer <token>`，不匹配返回 401 结构化错误；为空（默认）保持本地免鉴权。MCP 接入说明页 SHALL 在鉴权开启时展示带 header 的接入命令。

#### Scenario: 未携带 token 被拒
- **WHEN** MCP_AUTH_TOKEN 已设置且请求未带 Authorization 头
- **THEN** 返回 401，不泄露任何项目数据

#### Scenario: 默认关闭零影响
- **WHEN** MCP_AUTH_TOKEN 为空
- **THEN** /mcp 行为与 M3 完全一致，无需任何客户端改动
