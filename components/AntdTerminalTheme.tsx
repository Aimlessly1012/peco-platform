"use client";

// antd v5 官方只支持 React 16~18，本项目是 React 19：这个补丁把 Modal/message/
// notification 等仍走旧渲染 API 的组件接到新的 createRoot 上。不引它不只是控制台
// 报兼容警告——那几个组件在 React 19 下会真的不工作。必须在任何 antd 组件之前引入。
import "@ant-design/v5-patch-for-react-19";

import { ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";

/**
 * 把 antd 拉进终端风（M12 D4）。
 *
 * 不改组件、只换 token：主色换成 accent 绿、圆角一律 0、字体走 IBM Plex Mono、
 * 边框/背景对齐 line/panel/shade。否则 antd 一副默认蓝加圆角的样子，和站里其他页面
 * 明显割裂。
 */

const TOKENS = {
  paper: "#f5f4ef",
  panel: "#ffffff",
  shade: "#faf9f5",
  line: "#d9d7cf",
  hair: "#eceae3",
  ink: "#17171a",
  ink2: "#4a4842",
  muted: "#6f6d66",
  faint: "#a8a69e",
  accent: "#0e7a45",
  danger: "#b8422f",
} as const;

const MONO = '"IBM Plex Mono", "Noto Sans SC", ui-monospace, monospace';

export default function AntdTerminalTheme({ children }: { children: React.ReactNode }) {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: TOKENS.accent,
          colorInfo: TOKENS.accent,
          colorError: TOKENS.danger,
          colorText: TOKENS.ink,
          colorTextSecondary: TOKENS.ink2,
          colorTextTertiary: TOKENS.muted,
          colorTextQuaternary: TOKENS.faint,
          colorBorder: TOKENS.line,
          colorBorderSecondary: TOKENS.hair,
          colorBgContainer: TOKENS.panel,
          colorBgLayout: TOKENS.paper,
          colorBgElevated: TOKENS.panel,
          colorFillAlter: TOKENS.shade,
          // 终端风：一律直角
          borderRadius: 0,
          borderRadiusLG: 0,
          borderRadiusSM: 0,
          borderRadiusXS: 0,
          fontFamily: MONO,
          fontSize: 13,
          controlHeight: 34,
          wireframe: true,
        },
        components: {
          Button: { primaryShadow: "none", defaultShadow: "none", dangerShadow: "none" },
          Card: { headerBg: TOKENS.shade },
          Table: { headerBg: TOKENS.shade, headerColor: TOKENS.muted },
          Segmented: { itemSelectedBg: TOKENS.accent, itemSelectedColor: TOKENS.paper },
        },
      }}
    >
      {children}
    </ConfigProvider>
  );
}
