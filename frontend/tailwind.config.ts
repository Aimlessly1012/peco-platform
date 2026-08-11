import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

export default {
  // lib/ 里的 labels.ts 也写类名（状态徽标、模块分组配色），必须纳入扫描
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: "#f5f4ef",
        panel: "#ffffff",
        canvas: "#efeee8",
        shade: "#faf9f5",
        line: "#d9d7cf",
        hair: "#eceae3",
        ink: "#17171a",
        ink2: "#4a4842",
        muted: "#6f6d66",
        dim: "#8a8880",
        faint: "#a8a69e",
        accent: "#0e7a45",
        danger: "#b8422f",
      },
      fontFamily: {
        mono: ['"IBM Plex Mono"', '"Noto Sans SC"', "ui-monospace", "monospace"],
      },
      letterSpacing: { label: "0.12em", wide: "0.06em" },
    },
  },
  plugins: [typography],
} satisfies Config;
