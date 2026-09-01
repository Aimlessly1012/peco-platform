import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

// dev 与 build/start 各用一个 distDir：两者共用 .next 时，dev server 跑着再执行
// npm run build 会覆盖 dev 的清单文件，页面 CSS 404 变裸 HTML，只能 rm -rf .next 重启
const nextConfig = (phase: string): NextConfig => ({
  // 容器部署要的产物形态：只带运行时依赖，镜像小、启动快
  output: "standalone",
  distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next" : ".next-build",
  // 钉住 tracing root：上层目录若有 lockfile（如 git worktree 场景），Next 会把
  // workspace root 猜到上面去，standalone 里 server.js 会被嵌进深层子路径
  outputFileTracingRoot: __dirname,
});

export default nextConfig;
