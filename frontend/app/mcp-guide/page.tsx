"use client";

import { useEffect, useState } from "react";
import CopyButton from "@/components/CopyButton";
import { mcpEndpoint } from "@/lib/api";

const addCommand = (url: string) =>
  `claude mcp add --transport http rag-coder ${url}`;

const TOOLS: { name: string; usage: string; args: string }[] = [
  {
    name: "list_projects",
    usage: "列出已录入的项目及索引状态、模块数与语言分布",
    args: "—",
  },
  {
    name: "get_project_overview",
    usage: "项目总览：项目级摘要 + 模块清单（名称/类型/路由前缀/摘要摘录）",
    args: "project",
  },
  {
    name: "get_module_map",
    usage: "功能地图：mermaid 思维导图源码 + 各模块的文件清单",
    args: "project",
  },
  {
    name: "search_code",
    usage: "语义检索代码片段，返回文件路径 + 行号区间 + 符号 + 代码片段",
    args: "project, query, module?, top_k≤20",
  },
  {
    name: "get_file_summary",
    usage: "单文件说明：文件摘要、符号表、imports 与 imported_by",
    args: "project, path",
  },
  {
    name: "impact_analysis",
    usage: "一跳影响面反查：谁 import 它、哪些前端代码块调它、波及哪些模块",
    args: "project, file_or_symbol",
  },
  {
    name: "get_project_understanding",
    usage: "读取理解报告三件套：需求逻辑文档、思维导图、核心流程时序图",
    args: "project",
  },
];

function CommandBlock({ command, label }: { command: string; label?: string }) {
  return (
    <div className="flex items-start gap-2 border border-line bg-shade px-3 py-2.5">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre text-[11.5px] leading-relaxed text-ink2">
        {command}
      </code>
      <CopyButton text={command} label={label ?? "COPY"} className="shrink-0" />
    </div>
  );
}

function Step({
  index,
  title,
  hint,
  command,
}: {
  index: number;
  title: string;
  hint: React.ReactNode;
  command: string;
}) {
  return (
    <li className="flex gap-3.5">
      <span className="flex h-5 w-5 flex-none items-center justify-center bg-accent text-[10px] text-paper">
        {index}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[12.5px] font-medium">{title}</div>
        <p className="mt-1 text-[11px] leading-relaxed text-muted">{hint}</p>
        <div className="mt-2.5">
          <CommandBlock command={command} />
        </div>
      </div>
    </li>
  );
}

export default function McpGuidePage() {
  // 子路径部署下 API_BASE 是相对路径，挂载后用当前站点 origin 补成可执行的绝对 URL
  const [mcpUrl, setMcpUrl] = useState(() => mcpEndpoint());
  useEffect(() => {
    setMcpUrl(mcpEndpoint(window.location.origin));
  }, []);
  const ADD_COMMAND = addCommand(mcpUrl);

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左栏：端点信息 */}
      <aside className="hidden w-[212px] flex-none flex-col gap-7 overflow-y-auto border-r border-line bg-canvas px-5 py-6 md:flex">
        <div className="flex flex-col gap-1.5">
          <div className="text-[10px] tracking-label text-dim">MCP TOOLS</div>
          <div className="text-[38px] font-semibold leading-none">07</div>
          <div className="text-[11px] text-muted">streamable-http</div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[10px] tracking-label text-dim">ENDPOINT</div>
          <div className="break-all text-[11px] text-muted">{mcpUrl}</div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[10px] tracking-label text-dim">CLIENT</div>
          <div className="text-[11px] text-muted">Claude Code</div>
        </div>

        <div className="mt-auto text-[11px] leading-relaxed text-faint">
          端点随后端进程启停
          <br />
          <span className="text-muted">docker compose up -d</span>
        </div>
      </aside>

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col gap-6 overflow-y-auto px-7 py-6">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[22px] font-semibold">MCP 接入</h1>
          <span className="text-[11px] text-dim">
            $ claude mcp add<span className="text-accent">_</span>
          </span>
        </div>

        <p className="max-w-3xl text-[12px] leading-relaxed text-muted">
          把本服务作为 MCP Server 接入 Claude Code，agent 即可直接检索本地已索引仓库的代码与理解报告。
          传输方式 streamable-http，端点随后端进程一同启停（后端未启动时接入会失败）。
        </p>

        <section className="border border-line bg-panel">
          <div className="flex items-center gap-2.5 border-b border-line bg-shade px-4 py-2.5">
            <span className="block h-2 w-2 bg-accent" />
            <span className="text-[10px] tracking-label text-dim">SERVER URL</span>
          </div>
          <div className="p-4">
            <CommandBlock command={mcpUrl} label="COPY URL" />
          </div>
        </section>

        <section className="border border-line bg-panel">
          <div className="flex items-center gap-2.5 border-b border-line bg-shade px-4 py-2.5">
            <span className="block h-2 w-2 bg-accent" />
            <span className="text-[10px] tracking-label text-dim">SETUP</span>
          </div>
          <ol className="flex flex-col gap-5 p-4">
            <Step
              index={1}
              title="确认服务已启动"
              hint="在项目根目录执行，后端监听 8001 端口。"
              command="docker compose up -d"
            />
            <Step
              index={2}
              title="添加到 Claude Code"
              hint={
                <>
                  在任意仓库目录执行一次即可（加 <code className="text-accent">--scope user</code>{" "}
                  可全局生效）。
                </>
              }
              command={ADD_COMMAND}
            />
            <Step
              index={3}
              title="验证连接"
              hint={
                <>
                  下面的命令应看到 rag-coder 已连接；在 Claude Code 会话中输入{" "}
                  <code className="text-accent">/mcp</code> 可查看 7 个工具。
                </>
              }
              command="claude mcp list"
            />
          </ol>
        </section>

        <section className="border border-line bg-panel">
          <div className="flex items-center gap-2.5 border-b border-line bg-shade px-4 py-2.5">
            <span className="block h-2 w-2 bg-accent" />
            <span className="text-[10px] tracking-label text-dim">TOOLS · 7</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-[12px]">
              <thead className="border-b border-line bg-shade text-left text-[10px] tracking-label text-dim">
                <tr>
                  <th className="px-4 py-2.5 font-normal">TOOL</th>
                  <th className="px-4 py-2.5 font-normal">用途</th>
                  <th className="px-4 py-2.5 font-normal">ARGS</th>
                </tr>
              </thead>
              <tbody>
                {TOOLS.map((t) => (
                  <tr key={t.name} className="border-b border-hair align-top last:border-b-0">
                    <td className="px-4 py-3 text-[11.5px] text-ink">{t.name}</td>
                    <td className="px-4 py-3 leading-relaxed text-ink2">{t.usage}</td>
                    <td className="px-4 py-3 text-[11px] text-muted">{t.args}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="border border-line bg-panel p-4">
          <div className="text-[10px] tracking-label text-dim">NOTES</div>
          <ul className="mt-2.5 flex flex-col gap-1.5 text-[11px] leading-relaxed text-muted">
            <li>
              <span className="text-accent">·</span> <code>project</code>{" "}
              参数可传项目名称或项目 uuid；重名时取最新创建的那个，返回中会带{" "}
              <code>resolved_project_id</code>，需要精确指定时直接传 uuid。
            </li>
            <li>
              <span className="text-accent">·</span>{" "}
              所有代码定位统一为「文件路径 + 行号区间」，可直接拿去打开文件或做二次检索。
            </li>
            <li>
              <span className="text-accent">·</span>{" "}
              项目不存在、索引未完成或参数非法时，工具返回结构化错误说明，不会中断 MCP 连接。
            </li>
            <li>
              <span className="text-accent">·</span>{" "}
              仓库更新后需要在项目列表页重新索引，MCP 读取的是最近一次索引的结果。
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
