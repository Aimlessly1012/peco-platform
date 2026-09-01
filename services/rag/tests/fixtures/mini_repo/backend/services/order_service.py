import uuid


class OrderService:
    """订单业务逻辑：创建、列表、取消（内存存储）"""

    def __init__(self):
        self._orders: dict[str, dict] = {}

    def list_all(self) -> list[dict]:
        return list(self._orders.values())

    def create(self, payload: dict) -> dict:
        order_id = uuid.uuid4().hex[:8]
        order = {
            "id": order_id,
            "items": payload["items"],
            "total": sum(i.get("price", 0) * i.get("qty", 1) for i in payload["items"]),
            "status": "created",
        }
        self._orders[order_id] = order
        return order

    def cancel(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None:
            return False
        order["status"] = "cancelled"
        return True
