"""报告链路的共享测试夹具（M17 1.5：从 test_report.py 下沉）。

放这里而不是留在某个 test_ 文件里，是因为它被 6 个测试文件用到——测试文件互相
import 会让"改 A 的实现顺手碰坏 B"，spec 明确要求这类夹具收敛到 helpers。
"""
from app.services.report.graph_reader import (
    ApiEdgeInfo,
    FileNode,
    GraphEdges,
    ImportEdgeInfo,
    ModuleNode,
    ProjectTree,
)


GOOD_FLOW_OUTPUT = """## 下单流程
```mermaid
flowchart TD
    A[用户选择商品] --> B[提交订单]
    B --> C{是否有库存}
    C -->|有| D[生成订单]
    C -->|无| E[提示缺货]
```

## 取消流程
```mermaid
flowchart TD
    A[用户申请取消] --> B[系统校验状态]
    B --> C[释放库存]
```"""

GOOD_SEQ = """sequenceDiagram
    participant U as 用户
    participant FE as 订单页面
    participant BE as 订单接口
    U->>FE: 打开订单列表
    FE->>BE: GET /api/orders
    BE-->>FE: 返回订单数组
    FE-->>U: 渲染列表"""


def make_tree() -> ProjectTree:
    """两个核心模块（api/page，文件≥2）+ 一个单文件模块 + 一个 shared 模块。"""
    return ProjectTree(
        project_id="p1",
        name="mini-shop",
        summary="全栈演示项目：订单与用户",
        modules=[
            ModuleNode(
                key="api:orders", name="orders", kind="api", route_prefix="/api/orders",
                summary="订单接口模块：创建与查询订单",
                files=[
                    FileNode(path="backend/routers/orders.py", language="python", summary="订单路由"),
                    FileNode(path="backend/services/order_service.py", language="python", summary="订单服务"),
                ],
            ),
            ModuleNode(
                key="page:orders", name="orders", kind="page", route_prefix="/orders",
                summary="订单页面模块",
                files=[
                    FileNode(path="frontend/pages/orders.tsx", language="typescript", summary="订单页"),
                    FileNode(path="frontend/components/OrderCard.tsx", language="typescript", summary="订单卡片"),
                    FileNode(path="frontend/lib/api.ts", language="typescript", summary="接口封装"),
                ],
            ),
            ModuleNode(
                key="api:users", name="users", kind="api", route_prefix="/api/users",
                summary="用户接口模块",
                files=[FileNode(path="backend/routers/users.py", language="python", summary="用户路由")],
            ),
            ModuleNode(
                key="shared:shared", name="shared", kind="shared",
                files=[FileNode(path="backend/models.py", language="python", summary="数据模型")],
            ),
        ],
    )


def make_edges() -> GraphEdges:
    return GraphEdges(
        api_edges=[
            ApiEdgeInfo(
                src_file="frontend/lib/api.ts", src_symbol="apiGet", src_start=10,
                dst_file="backend/routers/orders.py", dst_symbol="list_orders", dst_start=20,
            ),
            ApiEdgeInfo(
                src_file="frontend/pages/orders.tsx", src_symbol="OrdersPage", src_start=5,
                dst_file="backend/routers/orders.py", dst_symbol="create_order", dst_start=40,
            ),
        ],
        import_edges=[
            ImportEdgeInfo(src="backend/routers/orders.py", dst="backend/services/order_service.py"),
            ImportEdgeInfo(src="frontend/pages/orders.tsx", dst="frontend/lib/api.ts"),
            ImportEdgeInfo(src="frontend/pages/orders.tsx", dst="frontend/components/OrderCard.tsx"),
        ],
    )


class FakeLLM:
    """可编程假 LLM。

    chapter_returns 按批次依次取值（支持值、None、异常实例）；给单个值时所有批次复用它。
    """

    def __init__(
        self, chapter_returns=None, overview_returns="## 一、系统概述\n\n概述正文",
        seq_returns=None, feature_returns="- 创建订单\n- 查询订单列表\n- 取消订单",
        flow_returns=None, group_returns=None,
    ):
        self.chapter_returns = chapter_returns
        self.overview_returns = overview_returns
        self.seq_returns = list(seq_returns or [])
        self.feature_returns = feature_returns
        self.flow_returns = flow_returns if flow_returns is not None else GOOD_FLOW_OUTPUT
        self.chapter_calls: list[dict] = []
        self.overview_calls: list[tuple] = []
        self.seq_calls: list[dict] = []
        self.feature_calls: list[dict] = []
        self.flow_calls: list[dict] = []
        self.group_returns = group_returns
        self.group_calls: list[dict] = []

    async def group_domains(self, domain_lines, count, min_groups=3, max_groups=10):
        self.group_calls.append({"domain_lines": domain_lines, "count": count})
        value = self.group_returns
        if isinstance(value, list):  # 序列：按调用次数依次返回，用于测重试
            idx = min(len(self.group_calls), len(value)) - 1
            value = value[idx]
        if isinstance(value, Exception):
            raise value
        return value

    async def generate_business_flows(
        self, flow_lines, module_flows, max_flows=4, max_nodes=8, retry_reason=""
    ):
        self.flow_calls.append(
            {"flow_lines": flow_lines, "module_flows": module_flows,
             "retry_reason": retry_reason}
        )
        value = self.flow_returns
        if isinstance(value, list):
            index = len(self.flow_calls) - 1
            value = value[index] if index < len(value) else None
        if isinstance(value, Exception):
            raise value
        return value

    async def generate_features(self, name, kind_label, route_prefix, summary, anchors):
        self.feature_calls.append(
            {"name": name, "kind_label": kind_label, "prefix": route_prefix,
             "summary": summary, "anchors": anchors}
        )
        value = self.feature_returns
        if isinstance(value, dict):          # 按模块名定制返回
            value = value.get(name)
        if isinstance(value, list):          # 按调用次序取值（测重试）
            index = len(self.feature_calls) - 1
            value = value[index] if index < len(value) else None
        if isinstance(value, Exception):
            raise value
        return value

    async def generate_chapters(self, module_blocks, count):
        self.chapter_calls.append({"blocks": module_blocks, "count": count})
        value = self.chapter_returns
        if isinstance(value, list):
            index = len(self.chapter_calls) - 1
            value = value[index] if index < len(value) else None
        if isinstance(value, Exception):
            raise value
        if value is None:
            return None
        return value if isinstance(value, str) else str(value)

    async def generate_overview(self, overview, module_lines, chapter_titles):
        self.overview_calls.append((overview, module_lines, chapter_titles))
        if isinstance(self.overview_returns, Exception):
            raise self.overview_returns
        return self.overview_returns

    async def generate_sequence(
        self, name, kind, prefix, summary, entry_summaries,
        api_lines, import_lines, retry_reason="",
    ):
        self.seq_calls.append({"name": name, "retry_reason": retry_reason})
        if not self.seq_returns:
            return None
        value = self.seq_returns.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


# ---------------- 思维导图（B2，程序化生成） ----------------
