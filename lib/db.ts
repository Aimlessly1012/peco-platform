import { Pool } from "pg";

/**
 * Postgres 连接池（与 RAG 后端共用同一个库）。
 *
 * 开发模式下 Next 会热重载模块，池子必须挂到 globalThis，否则每次改动都新建一个池，
 * 连接数很快耗尽。
 */
const globalForDb = globalThis as unknown as { pgPool?: Pool };

export function getPool(): Pool {
  if (!globalForDb.pgPool) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error("缺少 DATABASE_URL（见 .env.local.example）");
    }
    globalForDb.pgPool = new Pool({
      connectionString,
      max: 5,
      // 库连不上时快速失败，不要把请求挂死
      connectionTimeoutMillis: 5000,
      idle_in_transaction_session_timeout: 10000,
    });
  }
  return globalForDb.pgPool;
}

export async function query<T>(text: string, params?: unknown[]): Promise<T[]> {
  const res = await getPool().query(text, params);
  return res.rows as T[];
}
