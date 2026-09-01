from fastapi import FastAPI

from routers.orders import router as orders_router
from routers.users import router as users_router

app = FastAPI(title="Mini Shop")
app.include_router(orders_router, prefix="/api")
app.include_router(users_router, prefix="/api")


@app.get("/health")
def health():
    return {"ok": True}
