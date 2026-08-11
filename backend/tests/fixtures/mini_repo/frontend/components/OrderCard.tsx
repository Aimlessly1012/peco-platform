interface Props {
  order: { id: string; total: number; status: string };
}

export function OrderCard({ order }: Props) {
  return (
    <div className="order-card">
      <span>#{order.id}</span>
      <span>¥{order.total}</span>
      <b>{order.status}</b>
    </div>
  );
}
