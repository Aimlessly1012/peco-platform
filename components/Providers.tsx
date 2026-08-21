"use client";

import { SessionProvider } from "next-auth/react";

/** next-auth 的 SessionProvider 是 client 组件，root layout 需要它包一层。 */
export default function Providers({ children }: { children: React.ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
