/**
 * 前端即时拼装的 mermaid 源码（M5 D1）。
 *
 * 模块子导图的数据来自已加载的模块地图（GET /projects/{id}/modules），
 * 点击模块时本地拼串渲染，不产生后端请求、也不占后端存储。
 */
import type { ModuleInfo } from "./api";
import { moduleKindMeta } from "./labels";

/** 单张子导图最多画多少个文件节点，超出折叠成一个汇总节点。 */
export const MODULE_MINDMAP_FILE_LIMIT = 40;
/** 单个节点文案最长字符数，过长的路径从中间省略。 */
const MAX_LABEL = 56;

/**
 * 清洗节点文案，使其能安全放进 mermaid 的 ["..."] 里。
 *
 * mermaid 用双引号界定带特殊字符的节点文本，文本内部出现 " 会提前闭合；
 * 换行会破坏 mindmap 的缩进语义；反斜杠在部分版本里会被当转义起始。
 * 括号/方括号本身放在引号内是安全的，不必再处理。
 */
export function mermaidLabel(text: string): string {
  return (text ?? "")
    .replace(/\\/g, "/")
    .replace(/"/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

/** 过长路径中间省略，保留最有信息量的头尾。 */
export function shortenPath(path: string, max = MAX_LABEL): string {
  const p = path ?? "";
  if (p.length <= max) return p;
  const keepTail = Math.floor((max - 3) * 0.6);
  const keepHead = max - 3 - keepTail;
  return `${p.slice(0, keepHead)}...${p.slice(-keepTail)}`;
}

/**
 * 拼一个模块的文件子导图（Module → Files 两层）。
 *
 * 节点一律写成 `id["文案"]`：显式 id 避免 mermaid 把 `[` 当作 id 的一部分，
 * 引号包裹让路径里的 `.` `/` `(` `-` 等字符不参与语法解析。
 */
export function buildModuleMindmap(
  m: ModuleInfo,
  limit = MODULE_MINDMAP_FILE_LIMIT
): string {
  const files = m.files ?? [];
  const meta = moduleKindMeta(m.kind);
  const parts = [meta.label, m.route_prefix, `${files.length} 文件`].filter(
    Boolean
  );
  const root = `${m.name} (${parts.join(" · ")})`;

  const lines = ["mindmap", `  root["${mermaidLabel(root)}"]`];
  files.slice(0, limit).forEach((f, i) => {
    lines.push(`    f${i}["${mermaidLabel(shortenPath(f.path))}"]`);
  });
  if (files.length > limit) {
    lines.push(`    fmore["…还有 ${files.length - limit} 个文件"]`);
  }
  if (files.length === 0) {
    lines.push(`    f_empty["（该模块没有文件记录）"]`);
  }
  return lines.join("\n");
}
