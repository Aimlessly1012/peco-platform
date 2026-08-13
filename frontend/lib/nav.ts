/**
 * 登录跳转相关的纯函数。
 *
 * 单独放 lib：不依赖 React/Next，便于独立验证——回跳地址是外部可控输入，
 * 挡开放重定向的逻辑必须可测。
 */

export const LOGIN_PATH = "/login";

/**
 * 只接受站内相对路径。
 *
 * 挡掉的形态：`//evil.com`（协议相对，浏览器当绝对地址）、`https://…`、
 * `javascript:`、以及不带前导斜杠的相对路径。注意这里的路径都是**不含 basePath**
 * 的形式（usePathname 就是这么给的），交给 router 时会自动补前缀。
 */
export function safeNext(value: string | null | undefined): string {
  if (!value) return "/";
  if (!value.startsWith("/")) return "/";
  // 第二个字符是斜杠或反斜杠都会被浏览器当成协议相对地址
  if (value[1] === "/" || value[1] === "\\") return "/";
  return value;
}

/** 未登录时要去的登录地址，带上回跳来源。 */
export function loginHref(from: string): string {
  const target = safeNext(from);
  return target === "/" || target.startsWith(LOGIN_PATH)
    ? LOGIN_PATH
    : `${LOGIN_PATH}?next=${encodeURIComponent(target)}`;
}
