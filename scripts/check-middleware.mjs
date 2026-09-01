#!/usr/bin/env node
/**
 * 校验 middleware 的 matcher 覆盖了注册表里每个受保护项目。
 *
 *   npm run check:middleware
 *
 * ## 为什么需要这个脚本
 *
 * 项目清单在 `lib/projects.ts`，导航与访问判断都从那里读——唯独
 * `middleware.ts` 的 `config.matcher` 读不了：Next 要求它是**静态字面量**，
 * 构建期静态解析，不能由数组计算得出。所以每加一个受保护项目，都要手写两条。
 *
 * 而那两条里正藏着一个陷阱：`"/rag/:path*"` **匹配不到 `/rag` 裸路径**。
 * commit 6eaef3d 踩过——未登录访问 `/rag` 直接放行，页面自己没挡住。
 * 只写 `:path*` 而漏掉裸路径，是个不会报错、不会白屏、只会悄悄敞开一个门的错误。
 *
 * 手写 + 会重复的坑 + 静默失败 = 必须有机器盯着。这就是这个脚本。
 *
 * ## 与 check:reference 同一哲学
 *
 * 新增文件的地方靠结构保证不出错；**改既有文件的地方必须有守卫**。
 * 同样地，宁可误报也不静默放过：matcher 写法超出可解析形态（用变量、模板串、
 * 展开运算符）时直接失败，而不是当作空数组通过——空数组会让守卫以为
 * 「没有受保护项目」，从而放行一切，那比报错危险得多。
 */
import ts from "typescript";
import { readFileSync, existsSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

const MIDDLEWARE = join(root, "middleware.ts");
const REGISTRY = join(root, "lib/projects.ts");

function fail(message) {
  console.error(message);
  process.exit(1);
}

/**
 * 从 middleware.ts 提取 `export const config = { matcher: [...] }`。
 *
 * 用 AST 而不是正则：正则碰到注释里的 `"/rag"`、跨行数组、尾逗号都会出错，
 * 而这个脚本的判断结果直接关系到「某个路由有没有被保护」。
 */
function extractMatcher(sourceFile) {
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    const exported = (statement.modifiers ?? []).some(
      (m) => m.kind === ts.SyntaxKind.ExportKeyword
    );
    if (!exported) continue;

    for (const decl of statement.declarationList.declarations) {
      if (!ts.isIdentifier(decl.name) || decl.name.text !== "config") continue;
      if (!decl.initializer || !ts.isObjectLiteralExpression(decl.initializer)) {
        fail("middleware.ts 的 export const config 不是对象字面量，无法静态校验。");
      }
      for (const prop of decl.initializer.properties) {
        if (!ts.isPropertyAssignment(prop)) continue;
        if (prop.name.getText(sourceFile) !== "matcher") continue;
        if (!ts.isArrayLiteralExpression(prop.initializer)) {
          fail(
            "middleware.ts 的 matcher 不是数组字面量（用了变量或表达式？）。\n" +
              "Next 要求它静态可解析，本脚本同理——请写成内联的字符串数组。"
          );
        }
        const entries = [];
        for (const el of prop.initializer.elements) {
          if (!ts.isStringLiteral(el)) {
            fail(
              `middleware.ts 的 matcher 含非字符串字面量元素：${el.getText(sourceFile)}\n` +
                "模板串与展开运算符都无法静态校验，请写成普通字符串。"
            );
          }
          entries.push(el.text);
        }
        return entries;
      }
      fail("middleware.ts 的 config 里没有 matcher 属性。");
    }
  }
  fail("middleware.ts 里找不到 export const config。");
}

/** 注册表也用 AST 读：它是 .ts，Node 直接 import 不了（同 gen-heitu-reference 的处境）。 */
async function readRegistry() {
  const transpiled = ts.transpileModule(readFileSync(REGISTRY, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      isolatedModules: true,
    },
  }).outputText;

  if (/^\s*import\s/m.test(transpiled)) {
    fail(`${relative(root, REGISTRY)} 转译后仍有 import 残留——该文件只能写 type-only import。`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(transpiled, "utf8").toString("base64")}`;
  const mod = await import(url);
  if (!Array.isArray(mod.PROJECTS)) fail(`${relative(root, REGISTRY)} 没有导出 PROJECTS 数组。`);
  return mod.PROJECTS;
}

// ── 主流程 ────────────────────────────────────────────────────────────

const sourceFile = ts.createSourceFile(
  MIDDLEWARE,
  readFileSync(MIDDLEWARE, "utf8"),
  ts.ScriptTarget.Latest,
  true
);
const matcher = extractMatcher(sourceFile);
const projects = await readRegistry();

const errors = [];
const hints = [];

for (const project of projects) {
  const { key, route, access } = project;

  // R1：注册了却没有页面目录，是死链——注册表说有，用户点进去 404
  const dir = join(root, "app", key);
  if (!existsSync(dir)) {
    errors.push(
      `${key}\n    注册表声明了 route ${route}，但 app/${key}/ 不存在——导航会指向 404。`
    );
  }

  if (access === "public") continue;

  // 受保护项目必须两条都在。缺裸路径是 6eaef3d 那个坑，单独点名。
  const missing = [`${route}`, `${route}/:path*`].filter((e) => !matcher.includes(e));
  if (missing.length > 0) {
    errors.push(
      `${key}（access: ${access}）\n    matcher 缺少：${missing.map((m) => `"${m}"`).join("、")}\n` +
        (missing.includes(route)
          ? `    缺的是**裸路径**——"${route}/:path*" 匹配不到 "${route}" 本身，\n` +
            `    未登录访问 ${route} 会直接放行。这正是 6eaef3d 踩过的坑。\n`
          : "") +
        `    在 middleware.ts 的 matcher 里补上即可。`
    );
  }
}

/**
 * 反向：matcher 里有、注册表里没有的条目。
 *
 * 只提示不报错——可能是尚未登记的开发中项目，也可能是删项目时漏清的残留。
 * 前者合理，后者无害（多挡一层不会敞开门），所以不作为失败条件。
 */
const known = new Set(projects.flatMap((p) => [p.route, `${p.route}/:path*`]));
for (const entry of matcher) {
  if (!known.has(entry)) {
    hints.push(`matcher 里的 "${entry}" 不属于注册表里任何项目（删项目时漏清？）`);
  }
}

for (const hint of hints) console.log(`· ${hint}`);

if (errors.length > 0) {
  console.error(`\nmiddleware 与注册表对不上，${errors.length} 处：\n`);
  for (const error of errors) console.error(`  ✗ ${error}\n`);
  process.exit(1);
}

const guarded = projects.filter((p) => p.access !== "public");
console.log(
  `检查通过：${guarded.length} 个受保护项目（${guarded.map((p) => p.key).join("、")}）` +
    `的 matcher 覆盖完整，共 ${matcher.length} 条。`
);
