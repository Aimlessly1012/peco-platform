/**
 * 文件路径展示工具。
 *
 * 深层项目的路径动辄 8-9 段，直接 truncate 会把最有信息量的文件名截掉
 * （变成 "src/c…"）。这里统一走「首段 + … + 末两段」的中段省略，
 * 完整路径放 title，窄容器下再由 break-all 兜底。
 */

/** 末尾的行号区间（`:12-40`）不参与路径分段。 */
const LINE_RANGE = /(:\d+(?:-\d+)?)$/;

function splitLineRange(value: string): [string, string] {
  const m = value.match(LINE_RANGE);
  return m ? [value.slice(0, m.index), m[1]] : [value, ""];
}

export function basename(path: string): string {
  const [p] = splitLineRange(path);
  const segs = p.split("/").filter(Boolean);
  return segs[segs.length - 1] ?? p;
}

export function dirname(path: string): string {
  const [p] = splitLineRange(path);
  const segs = p.split("/").filter(Boolean);
  return segs.slice(0, -1).join("/");
}

/**
 * 中段省略：保留首段与末 `keepTail` 段。
 * `src/components/medicineModal/form/items/PackingScaleFormItem.tsx`
 *   → `src/…/items/PackingScaleFormItem.tsx`
 */
export function middleEllipsis(path: string, keepTail = 2): string {
  const [p, range] = splitLineRange(path);
  const segs = p.split("/").filter(Boolean);
  if (segs.length <= keepTail + 2) return path;
  const head = segs[0];
  const tail = segs.slice(-keepTail);
  const prefix = p.startsWith("/") ? "/" : "";
  return `${prefix}${[head, "…", ...tail].join("/")}${range}`;
}

/** 看起来像文件路径的 inline code：含 `/` 且以扩展名（可带行号）结尾。 */
export function looksLikePath(text: string): boolean {
  const t = text.trim();
  if (!t || t.includes(" ") || t.includes("\n") || !t.includes("/")) return false;
  const [p] = splitLineRange(t);
  return /\.[A-Za-z0-9]{1,8}$/.test(p);
}

/** 单行路径：中段省略 + 全路径 title；容器过窄时 break-all 而不是撑破布局。 */
export default function PathText({
  value,
  keepTail = 2,
  className = "",
}: {
  value: string;
  keepTail?: number;
  className?: string;
}) {
  const shown = middleEllipsis(value, keepTail);
  return (
    <span title={shown === value ? undefined : value} className={`break-all ${className}`}>
      {shown}
    </span>
  );
}
