# 字体自托管说明

界面字体（IBM Plex Mono + Noto Sans SC）**不走 Google Fonts CDN**，全部随仓库分发、由前端容器自己提供。内网、离线或 CDN 被墙的环境下排版与线上一致。

## 文件

| 路径 | 说明 |
|---|---|
| `fonts/*.woff2` | 318 个字体分片，约 13 MB。经 webpack 打包到 `.next/static/media/`（带内容 hash） |
| `app/fonts.css` | 318 条 `@font-face`，**由脚本生成，不要手改** |
| `scripts/fetch-fonts.py` | 抓取/更新字体的脚本 |
| `app/layout.tsx` | `import "./fonts.css"` 在 `globals.css` 之前引入 |

`tailwind.config.ts` 的 `fontFamily.mono` 引用这两个字体族，`globals.css` 把 `font-mono` 应用到 `body`。

**字体为什么不放 `public/`**：`public/` 里的文件只能用绝对路径 `/fonts/x.woff2` 引用，而 Next 的 `basePath` 不会重写 CSS 里的绝对 URL——子路径部署（`NEXT_PUBLIC_BASE_PATH=/rag`）时这些请求会打到 `/fonts/...` 而不是 `/rag/fonts/...`，全部 404。放在 `fonts/` 由 webpack 处理后，产物 URL 变成 `/rag/_next/static/media/xxx.<hash>.woff2`，前缀自动跟随，还白拿了内容 hash 长期缓存。

## 为什么是 318 个文件

Google Fonts 把中文字体按 `unicode-range` 切成上百个分片，这是刻意保留的：**浏览器只会下载页面实际用到的分片**。一屏中文界面通常只命中 2～5 个分片（几十 KB），不会一次拉 13 MB。合成一个大文件反而会让首屏变慢。

拆分构成：

- IBM Plex Mono：15 个（3 字重 × latin / latin-ext / cyrillic / cyrillic-ext / vietnamese）
- Noto Sans SC：303 个（3 字重 × 101 个中日韩分片）

如果嫌仓库体积大，可以砍掉 `500` 字重的中文分片（约 4.3 MB）——代价是 `font-medium` 的中文会由 400 合成加粗，与设计稿有细微出入。改法：编辑 `scripts/fetch-fonts.py` 里 `CSS_URL` 的 `Noto+Sans+SC:wght@400;500;700` 为 `400;700`，重跑脚本。

## 更新字体

换字体、加字重或升级字体版本时，在 `frontend/` 下执行：

```bash
python3 scripts/fetch-fonts.py
```

脚本会重新拉取 Google Fonts CSS、下载全部 woff2 到 `fonts/`、清理不再需要的旧文件，并重新生成 `app/fonts.css`。只用 Python 标准库，无需额外依赖。改字体族或字重请先改脚本顶部的 `CSS_URL`，并同步 `tailwind.config.ts` 的 `fontFamily.mono`。

脚本是幂等的：字体没变时重跑，`fonts/` 的内容逐字节不变。

## 许可

- **IBM Plex Mono** — SIL Open Font License 1.1，© IBM Corp.
- **Noto Sans SC** — SIL Open Font License 1.1，© Google LLC.

两者均允许自托管与随软件再分发。OFL 要求保留版权与许可声明，本文件即为声明；对外分发本项目时请一并保留。
