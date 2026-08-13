/**
 * 子路径部署（M7）：Nginx 把 https://域名/rag/ 反代到本服务时，
 * 用 NEXT_PUBLIC_BASE_PATH=/rag 构建；不设 = 本机开发形态，完全不变。
 *
 * 注意 NEXT_PUBLIC_* 是构建期变量，必须在 `next build` 时就位（运行期注入无效），
 * 容器侧对应 Dockerfile 的 build ARG。
 */

// 容错 "rag" / "/rag/" 这类写法：Next 要求前导斜杠、且不能有尾部斜杠
const raw = (process.env.NEXT_PUBLIC_BASE_PATH || "").trim();
const basePath = raw ? `/${raw.replace(/^\/+|\/+$/g, "")}` : "";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  basePath,
  // 不另设 assetPrefix：basePath 已经会给 /_next/* 加前缀，
  // assetPrefix 只有把静态资源托到独立 CDN 域名时才需要。
};

export default nextConfig;
