"""容量护栏（M14）：项目槽位 + 磁盘剩余双护栏。

3.6G 单机上先撑不住的是 Neo4j 内存，而它随项目数增长——所以**主约束是项目数**，
磁盘只是兜底（design D1）。不做按仓库大小的精细配额：项目数就是内存的代理指标。

只拦新建。重索引与删除一律放行，删项目即时腾出槽位。
"""
import logging
import shutil
from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tables import Project

logger = logging.getLogger(__name__)

# 用 1024³ 而不是 10⁹：跟运维在服务器上 df -h 看到的数字对得上
BYTES_PER_GB = 1024**3
DISK_PATH = "/"


@dataclass(frozen=True)
class Capacity:
    projects_used: int
    projects_limit: int
    disk_free_gb: float
    disk_total_gb: float
    accepting: bool
    # 只在 accepting=False 时非空，且已经是可直接展示的整句——前端不要再拼文案
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def disk_stats() -> tuple[float, float]:
    """(剩余, 总量)，单位 GB。

    design D2：backend 容器的 overlay fs 落在宿主盘上，statvfs 数字与宿主一致，
    量根目录即可，不必挂 /proc 或读宿主 mount。

    读盘失败返回 (0, 0) 表示"量不到"，由 evaluate 跳过磁盘那道护栏——
    槽位主护栏仍在，不至于因为一次 statvfs 抖动就把所有录入都拦掉。
    """
    try:
        usage = shutil.disk_usage(DISK_PATH)
    except OSError as e:
        logger.warning("读取磁盘用量失败（%s），本次跳过磁盘护栏", e)
        return 0.0, 0.0
    # 先取整再比较：用户看到的数字就是判定用的数字，不会出现
    # "条上写着剩 5.0G、阈值 5G，却说还能建"这种对不上的观感
    return round(usage.free / BYTES_PER_GB, 1), round(usage.total / BYTES_PER_GB, 1)


def evaluate(projects_used: int, free_gb: float, total_gb: float) -> tuple[bool, str]:
    """双护栏判定 → (accepting, reason)。两条都不满足时原因都给，省得用户删完项目才发现磁盘也不够。"""
    reasons: list[str] = []
    if projects_used >= settings.project_limit:
        reasons.append(
            f"项目槽位已满（{projects_used}/{settings.project_limit}），"
            "请先删除不再需要的项目"
        )
    if total_gb > 0 and free_gb <= settings.disk_min_free_gb:
        reasons.append(
            f"磁盘空间不足（剩余 {free_gb}G，阈值 {settings.disk_min_free_gb}G），"
            "请清理服务器磁盘"
        )
    return not reasons, "；".join(reasons)


async def get_capacity(session: AsyncSession) -> Capacity:
    """当前容量状态。计数不加锁——单机低并发下最坏超额 1 个，可接受（design D4）。"""
    used = await session.scalar(select(func.count()).select_from(Project)) or 0
    free_gb, total_gb = disk_stats()
    accepting, reason = evaluate(used, free_gb, total_gb)
    return Capacity(
        projects_used=used,
        projects_limit=settings.project_limit,
        disk_free_gb=free_gb,
        disk_total_gb=total_gb,
        accepting=accepting,
        reason=reason,
    )
