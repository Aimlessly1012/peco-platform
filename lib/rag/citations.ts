/**
 * 把答案正文里的 `[1]` `[2]` 引用标记变成可点击上标的 rehype 插件。
 *
 * 放在 lib 而不是组件里：它是纯 hast 变换，不碰 React，便于单独验证。
 */

/** hast 节点的最小结构（只用到遍历需要的字段）。 */
export interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

/** 引用标记：`[12]`。用 matchAll，每次调用重新构造避免 lastIndex 残留。 */
const CITE_PATTERN = /\[(\d+)\]/g;

/**
 * 文本节点里的 `[n]` → `<sup class="cite-ref">n</sup>`。
 *
 * 整棵 code/pre 子树跳过：代码里的 `[0]` 是数组下标，不是引用。
 * 手写遍历而非引 unist-util-visit，避免为这点逻辑多一个依赖。
 */
export function rehypeCitationRefs() {
  return (tree: HastNode) => {
    walk(tree);
  };
}

function walk(node: HastNode): void {
  const children = node.children;
  if (!children?.length) return;
  if (node.type === "element" && (node.tagName === "code" || node.tagName === "pre")) {
    return;
  }

  const next: HastNode[] = [];
  let changed = false;

  for (const child of children) {
    if (child.type !== "text" || !child.value) {
      walk(child);
      next.push(child);
      continue;
    }
    const matches = [...child.value.matchAll(CITE_PATTERN)];
    if (!matches.length) {
      next.push(child);
      continue;
    }
    changed = true;
    let last = 0;
    for (const m of matches) {
      const at = m.index ?? 0;
      if (at > last) next.push({ type: "text", value: child.value.slice(last, at) });
      next.push({
        type: "element",
        tagName: "sup",
        properties: { className: ["cite-ref"] },
        children: [{ type: "text", value: m[1] }],
      });
      last = at + m[0].length;
    }
    if (last < child.value.length) {
      next.push({ type: "text", value: child.value.slice(last) });
    }
  }

  if (changed) node.children = next;
}
