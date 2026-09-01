from dataclasses import dataclass, field


@dataclass
class OrderItem:
    sku: str
    qty: int
    price: float


@dataclass
class Order:
    id: str
    items: list[OrderItem] = field(default_factory=list)
    status: str = "created"
