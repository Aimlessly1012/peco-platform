import { SignJWT, jwtVerify } from "jose";
import type { JWT } from "next-auth/jwt";

/**
 * NextAuth 会话 token 的 JWS(HS256) 编解码（M12 D2）。
 *
 * 为什么不用 NextAuth 默认的 JWE：RAG 的 FastAPI 后端要用同一个密钥直接验签
 * cookie，签名（可验）而非加密（要解）才做得到，这样浏览器可以直连后端，
 * SSE 与 MCP 链路一个字节不用改。
 *
 * **为什么抽成独立文件（血的教训）**：这套编解码最初只写在 lib/auth.ts 的
 * authOptions 里，而 middleware 的 withAuth 内部自带一套默认解码（JWE），
 * 完全不知道 authOptions 的自定义——结果用户登录成功、首页正常，唯独进
 * middleware 保护的 /rag、/admin 被当成未登录踢回登录页。authOptions 与
 * middleware 必须共用同一实现，共用的唯一可靠方式就是放在同一个文件里。
 * （jose 走 Web Crypto，edge runtime 可用，middleware 里跑没问题。）
 */

const DEFAULT_MAX_AGE = 30 * 24 * 60 * 60;

export async function encodeSessionToken(params: {
  token?: JWT;
  secret: string | Buffer | unknown;
  maxAge?: number;
}): Promise<string> {
  const key = new TextEncoder().encode(String(params.secret));
  const now = Math.floor(Date.now() / 1000);
  return await new SignJWT({ ...(params.token ?? {}) })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt(now)
    .setExpirationTime(now + (params.maxAge ?? DEFAULT_MAX_AGE))
    .sign(key);
}

export async function decodeSessionToken(params: {
  token?: string;
  secret: string | Buffer | unknown;
}): Promise<JWT | null> {
  if (!params.token) return null;
  try {
    const key = new TextEncoder().encode(String(params.secret));
    const { payload } = await jwtVerify(params.token, key, {
      algorithms: ["HS256"],
    });
    return payload as JWT;
  } catch {
    // 过期、被篡改、或 JWS 改造前签发的旧 JWE token：一律当未登录，走重新登录
    return null;
  }
}
