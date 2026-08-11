from fastapi import APIRouter, HTTPException

from services.order_service import OrderService

router = APIRouter(tags=["orders"])
service = OrderService()


@router.get("/orders")
def list_orders():
    """订单列表接口"""
    return service.list_all()


@router.post("/orders")
def create_order(payload: dict):
    """创建订单：校验商品与数量后生成订单记录"""
    if not payload.get("items"):
        raise HTTPException(400, "订单不能为空")
    return service.create(payload)


@router.delete("/orders/{order_id}")
def cancel_order(order_id: str):
    """取消订单"""
    ok = service.cancel(order_id)
    if not ok:
        raise HTTPException(404, "订单不存在")
    return {"cancelled": order_id}
