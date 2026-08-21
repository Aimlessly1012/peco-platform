import { NextResponse } from "next/server";
import { HttpError, requireAdmin } from "@/lib/guard";
import { listUsers } from "@/lib/users";

// 查库的路由一律动态：不能在构建期连数据库
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    await requireAdmin();
    return NextResponse.json(await listUsers());
  } catch (e) {
    if (e instanceof HttpError) {
      return NextResponse.json({ detail: e.message }, { status: e.status });
    }
    return NextResponse.json(
      { detail: `读取用户失败：${(e as Error).message}` },
      { status: 500 }
    );
  }
}
