from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import orders, products, reports, webhooks
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Warehouse Manager API",
    description="Product inventory, order management, shipping labels, and reporting",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(products.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")


@app.get("/")
def root():
    return {"app": "Warehouse Manager", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}
