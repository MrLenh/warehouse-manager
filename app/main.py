import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import orders, products, reports, stock_requests, webhooks
from app.database import init_db

STATIC_DIR = pathlib.Path(__file__).parent / "static"


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
app.include_router(stock_requests.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/product/{product_id}")
def product_detail_page(product_id: str):
    """Product detail page - landing for QR code scans."""
    return FileResponse(STATIC_DIR / "product.html")


@app.get("/api/v1/config")
def get_config():
    """Expose public config (BASE_URL) for frontend."""
    from app.config import settings
    return {"base_url": settings.BASE_URL.rstrip("/")}


@app.get("/health")
def health():
    return {"status": "ok"}
