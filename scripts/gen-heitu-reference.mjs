#!/usr/bin/env node
/**
 * 从 node_modules/heitu 的 .d.ts 提取字段说明，生成 app/front/reference/generated.ts。
 *
 *   npm run gen:reference
 *
 * 展示哪些接口的哪些字段，由 app/front/reference/curation.ts 的策展清单决定（人写）；
 * 说明文本优先取源里的 TSDoc，源里没有才取同文件的覆盖层。
 *
 * ## 本脚本永不写 curation.ts
 *
 * 全文件只有一处 writeFileSync，目标是常量 OUT_FILE。合并生成物与手写物会让人补的
 * 覆盖条目在下次执行时被冲掉——这是 D-生成物与手写物分离 的由来。
 *
 * ## 失败即价值
 *
 * 三条失败路径（接口不存在 / 字段不存在 / 两处皆无说明）不是防御性代码，而是这套方案
 * 的目的本身：heitu 升级后改名、删字段、新增字段都会在这里响。既有的
 * app/front/demos/hooks-reference.ts 自称「与当前安装版本一致」却无人守护，正是要避免的样子。
 *
 * ## 不启用 TypeChecker
 *
 * 纯 ts.createSourceFile 按接口名定点提取。TypeChecker 能展开
 * `IFormRenderProps extends FormProps`，但继承一律不展开，展开能力反而要再加一层过滤
 * 把 antd 的字段剔回去，并引入对 antd 类型解析成功与否的隐性依赖。
 */
import ts from "typescript";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

/** `--check` 只验不写：跑完全部检查，并确认磁盘上的产物已是最新。给 CI 用的形态。 */
const CHECK = process.argv.includes("--check");

const DIST = join(root, "node_modules/heitu/dist");
const CURATION_FILE = join(root, "app/front/reference/curation.ts");
const OUT_FILE = join(root, "app/front/reference/generated.ts");

// ── 读源 ──────────────────────────────────────────────────────────────

/**
 * 收集 dist 下的 .d.ts，跳过 esm/ —— 那是同一批声明的第二份拷贝，
 * 不排除的话每个接口都会「重名」。
 */
function collectDts(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry !== "esm") collectDts(full, out);
    } else if (entry.endsWith(".d.ts")) {
      out.push(full);
    }
  }
  return out;
}

/**
 * TSDoc 描述文本。
 *
 * **保留换行**：dist 里有一批多行带 `-` 列表的 TSDoc（useWindowSize、useLocalStorage、
 * charts/core/Scale、canvas/core/shapes/drag 等），压成一行会糊成
 * 「。 - 始终调用 hook - 只在 set 时写入」。表格侧用 whitespace-pre-line 还原成真列表。
 */
function docOf(node) {
  return ts
    .getJSDocCommentsAndTags(node)
    .map((doc) => ts.getTextOfJSDocComment(doc.comment) ?? "")
    .filter(Boolean)
    .join("\n")
    .split("\n")
    .map((line) => line.trim())
    .join("\n")
    .trim();
}

/** 类型文本原样取自 .d.ts，只把换行与缩进压平，不做展开或简化。 */
function typeOf(member, sourceFile) {
  return member.type ? member.type.getText(sourceFile).replace(/\s+/g, " ").trim() : "unknown";
}

/**
 * 把一个类型声明的成员抽成 Map。
 *
 * 只认属性：方法（`draw()`、`inScope()`）与 private / protected 成员都是内部实现，
 * 不进橱窗。类成员一并处理，因为 canvas 的 Group 没有具名配置接口，
 * 其 `draggable` 只在 `declare class Group` 上。
 */
function membersOf(node, sourceFile) {
  const members = new Map();
  for (const member of node.members ?? []) {
    if (!ts.isPropertySignature(member) && !ts.isPropertyDeclaration(member)) continue;
    const hidden = (member.modifiers ?? []).some(
      (m) => m.kind === ts.SyntaxKind.PrivateKeyword || m.kind === ts.SyntaxKind.ProtectedKeyword
    );
    if (hidden || ts.isPrivateIdentifier(member.name)) continue;
    const name = member.name.getText(sourceFile);
    members.set(name, {
      name,
      type: typeOf(member, sourceFile),
      doc: docOf(member),
      optional: Boolean(member.questionToken),
    });
  }
  return members;
}

/**
 * 建「声明名 → 声明」索引。
 *
 * 遍历顶层语句而非只看 export，因为 canvas 的 ICircle 等接口未导出，但 AST 层面可见。
 * `interface X`、`type X = { ... }`、`declare class X` 对使用者是一回事，一并收进来——
 * Group 的 draggable 只存在于类声明上，不收类就做不出它的字段表。
 */
function indexDeclarations(files) {
  const index = new Map();
  for (const file of files) {
    const sourceFile = ts.createSourceFile(
      file,
      readFileSync(file, "utf8"),
      ts.ScriptTarget.Latest,
      true
    );
    for (const statement of sourceFile.statements) {
      let name = null;
      let node = null;
      if (ts.isInterfaceDeclaration(statement)) {
        name = statement.name.text;
        node = statement;
      } else if (ts.isTypeAliasDeclaration(statement) && ts.isTypeLiteralNode(statement.type)) {
        name = statement.name.text;
        node = statement.type;
      } else if (ts.isClassDeclaration(statement) && statement.name) {
        name = statement.name.text;
        node = statement;
      }
      if (!name) continue;
      if (!index.has(name)) index.set(name, []);
      index.get(name).push({
        file: relative(root, file),
        members: membersOf(node, sourceFile),
      });
    }
  }
  return index;
}

/**
 * 拼一条调用签名：`useAsyncFn<T>(fn: F, deps?: D) => R`。
 *
 * 逐段重建而不是对整个节点 getText——参数上挂着 TSDoc 的类型别名（useDeepCompareEffect
 * 就是），整节点取文本会把注释一起卷进签名。逐个 parameter 取则跳过前置 trivia。
 */
function signatureText(name, node, sourceFile) {
  const flat = (text) => text.replace(/\s+/g, " ").trim();
  const typeParams = node.typeParameters?.length
    ? `<${node.typeParameters.map((p) => flat(p.getText(sourceFile))).join(", ")}>`
    : "";
  const params = (node.parameters ?? []).map((p) => flat(p.getText(sourceFile))).join(", ");
  const returns = node.type ? flat(node.type.getText(sourceFile)) : "void";
  return `${name}${typeParams}(${params}) => ${returns}`;
}

/**
 * 建「函数名 → 调用签名」索引。
 *
 * hooks 的 19 个导出有三种声明形态：`declare function`（5 个）、
 * `declare const X: (…) => R` 内联函数类型（11 个）、`declare const X: SomeType`
 * 指向别处的函数类型别名（3 个，如 useWindowSize → UseWindowSize）。
 * 只认第一种会漏掉 14 个，所以三种都要收，第三种还要跨文件解引用。
 */
function indexFunctions(files) {
  const sources = files.map((file) => ({
    file: relative(DIST, file),
    sourceFile: ts.createSourceFile(
      file,
      readFileSync(file, "utf8"),
      ts.ScriptTarget.Latest,
      true
    ),
  }));

  // 先收全部类型别名，供第三种形态解引用
  const aliases = new Map();
  for (const { sourceFile } of sources) {
    for (const statement of sourceFile.statements) {
      if (ts.isTypeAliasDeclaration(statement)) {
        aliases.set(statement.name.text, { node: statement.type, sourceFile });
      }
    }
  }

  const index = new Map();
  const push = (name, entry) => {
    if (!index.has(name)) index.set(name, []);
    index.get(name).push(entry);
  };

  for (const { file, sourceFile } of sources) {
    for (const statement of sourceFile.statements) {
      if (ts.isFunctionDeclaration(statement) && statement.name) {
        const name = statement.name.text;
        push(name, { file, signature: signatureText(name, statement, sourceFile), doc: docOf(statement) });
        continue;
      }
      if (!ts.isVariableStatement(statement)) continue;

      for (const decl of statement.declarationList.declarations) {
        if (!ts.isIdentifier(decl.name) || !decl.type) continue;
        const name = decl.name.text;

        let signature = null;
        if (ts.isFunctionTypeNode(decl.type)) {
          signature = signatureText(name, decl.type, sourceFile);
        } else if (ts.isTypeReferenceNode(decl.type)) {
          const alias = aliases.get(decl.type.typeName.getText(sourceFile));
          if (alias && ts.isFunctionTypeNode(alias.node)) {
            signature = signatureText(name, alias.node, alias.sourceFile);
          }
        }
        if (!signature) continue; // 不是函数，与本索引无关

        // TSDoc 通常挂在 VariableStatement 上，偶尔在声明本身
        push(name, { file, signature, doc: docOf(statement) || docOf(decl) });
      }
    }
  }
  return index;
}

/**
 * 同名声明去重。
 *
 * dist 里确有重名：hooks 的 Options 在 usePolling 与 useWebSocket 各有一份，成员完全不同。
 * 静默取第一个会给出一张张冠李戴的字段表，比报错有害得多，所以成员不一致时失败。
 * 成员一致（同一份声明被两处 re-export）则取任一。
 */
function resolveDeclaration(candidates) {
  const signature = (decl) =>
    [...decl.members.values()].map((m) => `${m.name}:${m.type}`).sort().join("|");
  const first = signature(candidates[0]);
  const consistent = candidates.every((c) => signature(c) === first);
  return consistent ? { decl: candidates[0] } : { ambiguous: candidates.map((c) => c.file) };
}

// ── 读人写的一侧 ──────────────────────────────────────────────────────

/**
 * 读 curation.ts：转译后经 data: URL 动态 import。
 *
 * Node 20 不支持 --experimental-strip-types，.mjs 无法直接 import .ts；而把 curation
 * 退成 .mjs 会让它脱离 tsconfig 的类型检查——那是人要手写数十条覆盖的文件，最需要类型兜底。
 * 代价是 curation.ts 里只能有 type-only import（值导入会让转译产物的相对路径解析失败），
 * 该约束写在那个文件的头部。
 */
async function readCuration() {
  const transpiled = ts.transpileModule(readFileSync(CURATION_FILE, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      isolatedModules: true,
    },
  }).outputText;

  if (/^\s*import\s/m.test(transpiled)) {
    fail(
      `${relative(root, CURATION_FILE)} 转译后仍有 import 残留——该文件只能写 type-only import。`
    );
  }

  const url = `data:text/javascript;base64,${Buffer.from(transpiled, "utf8").toString("base64")}`;
  return import(url);
}

function fail(message) {
  console.error(message);
  process.exit(1);
}

// ── join ──────────────────────────────────────────────────────────────

/**
 * 说明取值：**人写的覆盖层优先**，其次源 TSDoc；两处皆无则记一条错误。
 *
 * 覆盖层的存在本身即代表人已做出判断，故优先——机器提取保证的是「不遗漏、不腐烂」，
 * 不是「最适合展示」。判 TSDoc 更好就删掉覆盖条目（usePrevious / useWindowSize 即如此），
 * 判人写更好就留着，判断结果由这条优先级承载。
 *
 * 两者并存时给一条**中性**提示：它是「这里有两份文本」的知会，不是「该删」的指令。
 */
function resolveDesc(key, doc, overrides, errors, hints, hintWhat) {
  const override = overrides[key];
  const desc = override || doc;
  if (!desc) {
    errors.push(
      `${key}\n    源里无 TSDoc，覆盖层也没有它——在 curation.ts 的 OVERRIDES 补一条 ` +
        `"${key}"，或把${hintWhat}移出清单。`
    );
    return null;
  }
  if (doc && override) {
    hints.push(`${key}  覆盖层与源 TSDoc 并存，采用覆盖层`);
  }
  return desc;
}

/**
 * 接口成员形态的一张表。
 */
function buildMemberTable(group, ctx, errors, hints) {
  const { title, interfaceName, fields, inheritedFrom, note } = group;
  const { declIndex, fnIndex, overrides } = ctx;

  if (!interfaceName) {
    errors.push(`${title}\n    members 形态缺 interfaceName。`);
    return null;
  }

  const candidates = declIndex.get(interfaceName);
  if (!candidates) {
    // 形态用错的典型：把 hooks 当接口点名。分开报比笼统的「不存在」好排查。
    if (fnIndex.has(interfaceName)) {
      errors.push(
        `${title}\n    ${interfaceName} 是函数声明，不是 interface / type / class。` +
          `这一组要改成函数形态：kind: "functions" + from。`
      );
    } else {
      errors.push(
        `${interfaceName}\n    ${relative(root, DIST)}/**/*.d.ts 里没有这个名字的 interface / type / class ` +
          `声明——heitu 可能改了名，或它本就不在包的类型声明里。`
      );
    }
    return null;
  }

  const resolved = resolveDeclaration(candidates);
  if (resolved.ambiguous) {
    errors.push(
      `${interfaceName}\n    在 ${resolved.ambiguous.length} 处声明且成员不同，无法确定取哪个：\n` +
        resolved.ambiguous.map((f) => `      ${f}`).join("\n")
    );
    return null;
  }

  const declared = resolved.decl.members;
  const rows = [];

  for (const field of fields) {
    const member = declared.get(field);
    if (!member) {
      errors.push(
        `${interfaceName}.${field}\n    字段不存在。${interfaceName} 现有字段：` +
          `${[...declared.keys()].join(", ") || "（无）"}`
      );
      continue;
    }

    const key = `${interfaceName}.${field}`;
    const desc = resolveDesc(key, member.doc, overrides, errors, hints, "该字段");
    if (desc) rows.push({ name: member.name, type: member.type, desc, optional: member.optional });
  }

  return { title, interfaceName, inheritedFrom, note, rows };
}

/**
 * 函数形态的一张表——hooks 那一类。
 *
 * 行的三列是「函数名 / 签名 / 说明」，与成员形态的「字段名 / 类型 / 说明」同构，
 * 所以产物仍是 FieldTable，页面不必分支。
 *
 * 覆盖层的键取 `${from}.${函数名}`（如 `hooks.useAsyncFn`）——函数没有宿主接口，
 * 但键的形状必须仍是「作用域.名称」，才能继续当漂移探针用。
 */
function buildFunctionTable(group, ctx, errors, hints) {
  const { title, from, fields, note } = group;
  const { declIndex, fnIndex, overrides, signatures } = ctx;

  if (!from) {
    errors.push(`${title}\n    functions 形态缺 from（dist 下的相对目录，如 "hooks"）。`);
    return null;
  }

  const scope = from.endsWith("/") ? from : `${from}/`;
  const inScope = (file) => file === from || file.startsWith(scope);
  const rows = [];

  for (const name of fields) {
    const candidates = (fnIndex.get(name) ?? []).filter((c) => inScope(c.file));
    if (candidates.length === 0) {
      if (declIndex.has(name)) {
        errors.push(
          `${title}\n    ${name} 是 interface / type / class，不是函数。` +
            `这一组要改成成员形态：去掉 kind，用 interfaceName + fields。`
        );
      } else {
        errors.push(
          `${from}.${name}\n    ${relative(root, DIST)}/${from} 下没有这个函数声明——` +
            `heitu 可能改了名，或它不在这个目录里。`
        );
      }
      continue;
    }
    // 同名函数在同一 scope 下重复声明时签名可能不同，取哪个都是猜，索性报错
    const distinct = new Set(candidates.map((c) => c.signature));
    if (distinct.size > 1) {
      errors.push(
        `${from}.${name}\n    在 ${candidates.length} 处声明且签名不同，无法确定取哪个：\n` +
          candidates.map((c) => `      ${c.file}`).join("\n")
      );
      continue;
    }

    const fn = candidates[0];
    const key = `${from}.${name}`;
    const desc = resolveDesc(key, fn.doc, overrides, errors, hints, "该函数");
    // 签名同理由人写优先：提取版保证不腐烂，但 useHtAxios 那条 814 字符会撑垮整张表
    if (desc) rows.push({ name, type: signatures[key] || fn.signature, desc, optional: false });
  }

  // 产物的 interfaceName 在函数形态下没有接口可填，用 from 表示来源作用域
  return { title, interfaceName: from, note, rows };
}

/**
 * 按 kind 分派。**必须显式分派**：curation.ts 受 tsc 检查而本脚本是 .mjs、不在 tsconfig 里，
 * 若默认走成员分支，functions 形态下 `group.interfaceName` 只会拿到 undefined 而静默出错。
 * 宁可响，不要静默（design D10）。
 */
function buildTables(groups, ctx, errors, hints) {
  const tables = [];
  for (const group of groups) {
    const kind = group.kind ?? "members";
    let table = null;
    if (kind === "members") {
      table = buildMemberTable(group, ctx, errors, hints);
    } else if (kind === "functions") {
      table = buildFunctionTable(group, ctx, errors, hints);
    } else {
      errors.push(
        `${group.title ?? "(无标题)"}\n    无法识别的 kind: ${JSON.stringify(kind)}——` +
          `只支持 "members"（缺省）与 "functions"。`
      );
    }
    if (table) tables.push(table);
  }
  return tables;
}

// ── 结果验证（R5 / 8.5）────────────────────────────────────────────────

/**
 * 人写的每一条，必须真的出现在产物里。
 *
 * 其余守卫查的都是「在不在」——接口在不在、字段在不在、说明空不空。它们对
 * 「字段在、说明不空、但取到的是错的那一份」完全无感：脚本零退出、页面不空白、无提示。
 * 本 change 期间这条缝被踩中两次（`const signatures = new Set(...)` 遮蔽了 SignatureMap，
 * 11 条人工签名恒 undefined；以及优先级反转前逐条判定保留的 4 条说明全被 TSDoc 盖过），
 * 两次都不是守卫发现的。
 *
 * 这里从「存在性」跨到「结果一致性」：写了 N 条，产物里就得能逐字找到 N 条。
 */
function verifyHandwritten(reference, overrides, signatures, errors) {
  const produced = new Map();
  for (const tab of reference) {
    for (const table of tab.tables) {
      for (const row of table.rows) produced.set(`${table.interfaceName}.${row.name}`, row);
    }
  }

  const clip = (text) => (text.length > 90 ? `${text.slice(0, 90)}…` : text).replace(/\n/g, "\\n");

  for (const [label, map, pick, what] of [
    ["OVERRIDES", overrides, (row) => row.desc, "说明"],
    ["SIGNATURES", signatures, (row) => row.type, "签名"],
  ]) {
    for (const [key, written] of Object.entries(map)) {
      const row = produced.get(key);
      if (!row) {
        errors.push(
          `${key}\n    ${label} 写了这条${what}，但产物里没有对应的行——键名写错，` +
            `或该字段/函数已不在清单里。`
        );
        continue;
      }
      const actual = pick(row);
      if (actual !== written) {
        errors.push(
          `${key}\n    ${label} 写了这条${what}，但产物采用的不是它：\n` +
            `      人写：${clip(written)}\n` +
            `      产物：${clip(actual)}`
        );
      }
    }
  }
}

// ── 写生成物 ──────────────────────────────────────────────────────────

const HEADER = `// ⚠️ 本文件由 scripts/gen-heitu-reference.mjs 生成，**不要手改**。
//
// 要改内容请改 curation.ts（策展清单与说明覆盖层），然后重跑：
//     npm run gen:reference
//
// 升级 heitu 之后同样要重跑——那时没人会去碰 curation.ts，产物却已经对不上新版本了。
// 校验用 npm run check:reference，退出码即结论。
//
// 与 app/fonts.css 同属「脚本生成、产物入库」的既有约定。产物入库不只是为了
// 构建期不依赖脚本——heitu 升级时字段变化会直接出现在 PR 的 diff 里，
// 「新增 smooth」「point 类型变了」一眼可见；构建期生成则完全不可见。
//
// 数据源：node_modules/heitu/dist/**/*.d.ts（不跨仓引用 ../heitu-platform，
// 容器构建时隔壁仓库不存在）。

import type { ReferenceTab } from "./types";
`;

function render(reference, version) {
  return `${HEADER}
/** 提取自 heitu@${version}。版本变了就该重跑，diff 里能看出字段的增删改。 */
export const REFERENCE: ReferenceTab[] = ${JSON.stringify(reference, null, 2)};
`;
}

// ── 主流程 ────────────────────────────────────────────────────────────

try {
  statSync(DIST);
} catch {
  fail(`找不到 ${relative(root, DIST)}——先 npm install。`);
}

const files = collectDts(DIST);
const curation = await readCuration();
// SIGNATURES 是后加的（D11），curation.ts 可能还没导出它
const { CURATION, OVERRIDES, SIGNATURES = {} } = curation;

const ctx = {
  declIndex: indexDeclarations(files),
  fnIndex: indexFunctions(files),
  overrides: OVERRIDES,
  signatures: SIGNATURES,
};

const errors = [];
const hints = [];

const reference = CURATION.map(({ tab, groups }) => ({
  tab,
  tables: buildTables(groups, ctx, errors, hints),
}));

// 结果验证只在结构无误时才有意义：字段若根本没提取出来，产物里当然没有对应行，
// 那时报「人写的没生效」是在重复同一个根因，会把真正的错误淹掉。
if (errors.length === 0) {
  verifyHandwritten(reference, OVERRIDES, SIGNATURES, errors);
}

// 提示先于错误打印；但只要有错误就不写文件——半对的生成物比不生成更难排查。
for (const hint of hints) console.log(`· ${hint}`);

if (errors.length > 0) {
  console.error(`\n生成失败，${errors.length} 处对不上：\n`);
  for (const error of errors) console.error(`  ✗ ${error}\n`);
  console.error(
    "接口/字段类的是 heitu 升级后内容漂移的信号；「产物采用的不是它」类的是人写内容没生效。\n" +
      "修 curation.ts 的清单、覆盖层或签名表，然后重跑。"
  );
  process.exit(1);
}

const version = JSON.parse(
  readFileSync(join(root, "node_modules/heitu/package.json"), "utf8")
).version;
const next = render(reference, version);
const current = (() => {
  try {
    return readFileSync(OUT_FILE, "utf8");
  } catch {
    return null;
  }
})();

const tableCount = reference.reduce((n, t) => n + t.tables.length, 0);
const rowCount = reference.reduce(
  (n, t) => n + t.tables.reduce((m, table) => m + table.rows.length, 0),
  0
);

const tally = `${tableCount} 张表 / ${rowCount} 个字段，heitu@${version}`;

if (CHECK) {
  // --check 只验不写。上面的检查已全部跑过（含结果验证），这里再比一次磁盘上的产物：
  // 生成物入库是 D6 的选择，代价就是有人得记着重跑（R1），这条能把「忘了重跑」也变成会响的。
  if (current !== next) {
    console.error(
      `${relative(root, OUT_FILE)} 与当前的 curation.ts / node_modules/heitu 不一致——` +
        `有人改了内容却没重跑。执行 npm run gen:reference 并把产物一起提交。`
    );
    process.exit(1);
  }
  console.log(`检查通过：产物是最新的，人写条目全部生效（${tally}）`);
} else if (current === next) {
  console.log(`generated.ts 无变化（${tally}）`);
} else {
  // 全文件唯一的写入点，目标是常量 OUT_FILE —— curation.ts 在任何路径下都不会被写。
  writeFileSync(OUT_FILE, next, "utf8");
  console.log(`已写入 ${relative(root, OUT_FILE)}（${tally}）`);
}

if (CURATION.length === 0) {
  console.log("策展清单为空——在 curation.ts 的 CURATION 里点名要展示的接口与字段。");
}
