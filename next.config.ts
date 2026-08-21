import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 容器部署要的产物形态：只带运行时依赖，镜像小、启动快
  output: "standalone",
};

export default nextConfig;
