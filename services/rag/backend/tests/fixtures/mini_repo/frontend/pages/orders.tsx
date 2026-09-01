import { useEffect, useState } from "react";
import { OrderCard } from "../components/OrderCard";
import { apiGet, apiPost } from "../lib/api";

interface Order {
  id: string;
  total: number;
  status: string;
}

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);

  useEffect(() => {
    apiGet<Order[]>("/api/orders").then(setOrders);
  }, []);

  const createDemo = async () => {
    await apiPost("/api/orders", { items: [{ sku: "demo", qty: 1, price: 9.9 }] });
    setOrders(await apiGet<Order[]>("/api/orders"));
  };

  return (
    <div>
      <h1>订单列表</h1>
      <button onClick={createDemo}>创建演示订单</button>
      {orders.map((o) => (
        <OrderCard key={o.id} order={o} />
      ))}
    </div>
  );
}
