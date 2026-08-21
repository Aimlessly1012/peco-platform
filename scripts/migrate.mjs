#!/usr/bin/env node
/**
 * 执行 migrations/ 下的 SQL（按文件名顺序）。
 *
 *   node scripts/migrate.mjs
 *
 * 每个文件都写成幂等的（CREATE TABLE IF NOT EXISTS 之类），重复跑安全。
 * 连接串取自 DATABASE_URL（.env.local 或环境变量）。
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

/** 没装 dotenv，手动读一下 .env.local 里的 DATABASE_URL。 */
function loadEnvLocal() {
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL;
  try {
    const text = readFileSync(join(root, ".env.local"), "utf8");
    const line = text.split("\n").find((l) => l.trim().startsWith("DATABASE_URL="));
    return line ? line.slice(line.indexOf("=") + 1).trim() : undefined;
  } catch {
    return undefined;
  }
}

const connectionString = loadEnvLocal();
if (!connectionString) {
  console.error("缺少 DATABASE_URL（放进 .env.local 或作为环境变量传入）");
  process.exit(1);
}

const dir = join(root, "migrations");
const files = readdirSync(dir).filter((f) => f.endsWith(".sql")).sort();
if (files.length === 0) {
  console.log("migrations/ 下没有 .sql 文件");
  process.exit(0);
}

const client = new pg.Client({ connectionString, connectionTimeoutMillis: 5000 });
try {
  await client.connect();
} catch (e) {
  console.error(`连接数据库失败：${e.message || e.code || e}`);
  console.error("确认 RAG 那套 compose 的 Postgres 正在运行（默认 localhost:5433）。");
  process.exit(1);
}

try {
  for (const f of files) {
    process.stdout.write(`→ ${f} `);
    await client.query(readFileSync(join(dir, f), "utf8"));
    console.log("OK");
  }
  const { rows } = await client.query(
    "SELECT COUNT(*)::text AS n FROM platform_users"
  );
  console.log(`\n完成。platform_users 现有 ${rows[0].n} 行。`);
} catch (e) {
  console.error(`\n执行失败：${e.message}`);
  process.exit(1);
} finally {
  await client.end();
}
