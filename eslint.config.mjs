import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    /**
     * 自 RAG Coder 迁入的代码（M12 阶段二）。
     *
     * 这两条规则是本仓库的 eslint-config-next 16 新加的，RAG 那边（config 15）没有。
     * 命中四处写法：useIndexProgress 的 latest-ref 模式与 effect 开头重置连接状态、
     * 聊天页 ThinkingIndicator 的 `startedAt ?? Date.now()` 兜底、详情页 dynamic 的
     * loading 组件工厂——都在 M6/M9 上线验证过，实时链路正跑在生产上。
     * 迁移的原则是「只统一令牌，不改结构与交互」，所以这里放宽规则而不是改代码；
     * 要重构的话应当单独立项，改完重新过一遍 SSE 与轮询回退的验收。
     */
    files: ["lib/rag/**/*.{ts,tsx}", "components/rag/**/*.{ts,tsx}", "app/rag/**/*.{ts,tsx}"],
    rules: {
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/purity": "off",
      "react/display-name": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
