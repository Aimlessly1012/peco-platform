import type { TabKey } from "../nav";
import type { FieldTable } from "./types";
import { REFERENCE } from "./generated";

/**
 * 字段说明表（M15）——四个 tab 共用的展示位。
 *
 * 数据全部来自 `generated.ts`，由 `npm run gen:reference` 从 heitu 的 .d.ts 提取。
 * 这里只管排版：内容对不对由脚本在生成期把关，页面上不会出现空白说明。
 *
 * 三列（字段 / 类型 / 说明），不设「默认值」列——heitu 的 TSDoc 没用 `@default` 标签，
 * 默认值写在描述文本里，单开一列会有过半为空。
 *
 * 表格样式与 HooksDemo 的签名表刻意保持一致：同一个页面里两套表格样式会显得像两个人做的。
 */

function Table({ table }: { table: FieldTable }) {
  return (
    <div className="flex min-w-0 flex-col border border-line">
      {/* 标题不作大写处理：页面别处的 CONFIG / NOTES 是纯 ASCII 标签，
          而这里的标题含接口名，大写会把 IItem 变成 IITEM。 */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line bg-shade px-3 py-2">
        <span className="text-[11px] text-ink2">{table.title}</span>
        <code className="text-[10.5px] text-faint">{table.interfaceName}</code>
        <span className="ml-auto text-[10px] text-faint">{table.rows.length} 个字段</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] text-[12px]">
          <thead className="border-b border-hair text-left text-[10px] tracking-label text-dim">
            <tr>
              <th className="px-3 py-2 font-normal">字段</th>
              <th className="w-[36%] px-3 py-2 font-normal">类型</th>
              <th className="px-3 py-2 font-normal">说明</th>
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <tr key={row.name} className="border-b border-hair align-top last:border-b-0">
                <td className="whitespace-nowrap px-3 py-2.5">
                  <code className="text-[11.5px] text-ink">{row.name}</code>
                  {/* `?` 是 TS 自己的可选标记，照搬即可，不另造徽标 */}
                  {row.optional && <span className="text-[11.5px] text-faint">?</span>}
                </td>
                <td className="px-3 py-2.5">
                  <code className="break-words text-[10.5px] leading-relaxed text-ink2">
                    {row.type}
                  </code>
                </td>
                {/* 保留换行：源里有一批多行带 `-` 列表的 TSDoc，压成一行会糊掉 */}
                <td className="whitespace-pre-line px-3 py-2.5 leading-relaxed text-muted">
                  {row.desc}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(table.inheritedFrom || table.note) && (
        <div className="flex flex-col gap-1 border-t border-hair bg-shade/40 px-3 py-2 text-[10.5px] leading-relaxed text-dim">
          {table.inheritedFrom && <p>↳ {table.inheritedFrom}</p>}
          {table.note && <p>{table.note}</p>}
        </div>
      )}
    </div>
  );
}

/**
 * 某个 tab 的全部字段表。清单为空时整块不渲染——铺开各 tab 的过程中，
 * 没轮到的 tab 不该先长出一个空壳。
 */
export default function FieldTables({ tab }: { tab: TabKey }) {
  const tables = REFERENCE.find((entry) => entry.tab === tab)?.tables ?? [];
  if (tables.length === 0) return null;

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline gap-2">
        <h3 className="text-[10px] tracking-label text-dim">字段说明</h3>
        <span className="text-[10px] text-faint">
          取自 heitu 类型声明，只列本页演示过的字段
        </span>
      </div>
      {tables.map((table) => (
        <Table key={table.interfaceName} table={table} />
      ))}
    </section>
  );
}
