import { NextResponse } from "next/server";
import { HttpError, requireAdmin } from "@/lib/guard";
import { applyAction, countActiveAdmins, getById, type UserAction } from "@/lib/users";

export const dynamic = "force-dynamic";

const ACTIONS: UserAction[] = ["approve", "reject", "disable", "enable"];

/**
 * 审核操作。两条自锁护栏在这里把关：
 * 不能动自己，也不能把最后一个可用管理员踢出去——少一条就能把自己锁在系统外。
 */
export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const admin = await requireAdmin();
    const { id } = await params;
    const body = (await req.json().catch(() => ({}))) as { action?: string };
    const action = body.action as UserAction | undefined;

    if (!action || !ACTIONS.includes(action)) {
      throw new HttpError(400, `action 必须是 ${ACTIONS.join(" / ")} 之一`);
    }

    const target = await getById(id);
    if (!target) throw new HttpError(404, "用户不存在");

    if (target.id === admin.id) {
      throw new HttpError(400, "不能对自己的账号执行审核操作");
    }
    // 降权类操作要确认还留得下管理员
    if (
      target.role === "admin" &&
      (action === "reject" || action === "disable") &&
      (await countActiveAdmins(target.id)) === 0
    ) {
      throw new HttpError(400, "这是最后一个可用的管理员，不能拒绝或禁用");
    }

    const updated = await applyAction(id, action);
    return NextResponse.json(updated);
  } catch (e) {
    if (e instanceof HttpError) {
      return NextResponse.json({ detail: e.message }, { status: e.status });
    }
    return NextResponse.json(
      { detail: `操作失败：${(e as Error).message}` },
      { status: 500 }
    );
  }
}
