import logging
import pathlib
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

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

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return JSON for unhandled exceptions so frontend can parse error."""
    logger.error("Unhandled error: %s\n%s", exc, traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": str(exc)})


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


@app.get("/order/{order_id}")
def order_detail_page(order_id: str):
    """Order detail page - landing for QR code scans."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/v1/config")
def get_config():
    """Expose public config (BASE_URL) for frontend."""
    from app.config import settings
    return {"base_url": settings.BASE_URL.rstrip("/")}


@app.get("/api/v1/shipping/defaults")
def get_shipping_defaults():
    """Return default carrier & service and warehouse address from config."""
    from app.config import settings
    return {
        "carrier": settings.DEFAULT_CARRIER,
        "service": settings.DEFAULT_SERVICE,
        "warehouse": {
            "name": settings.WAREHOUSE_NAME,
            "street1": settings.WAREHOUSE_STREET1,
            "city": settings.WAREHOUSE_CITY,
            "state": settings.WAREHOUSE_STATE,
            "zip": settings.WAREHOUSE_ZIP,
            "country": settings.WAREHOUSE_COUNTRY,
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/admin/clear-all-data")
def clear_all_data():
    """Temporary endpoint to clear all data from the database."""
    from app.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        tables = [
            "order_items", "orders", "stock_request_items",
            "stock_requests", "inventory_logs", "variants", "products",
        ]
        deleted = {}
        for tbl in tables:
            result = db.execute(text(f"DELETE FROM {tbl}"))
            deleted[tbl] = result.rowcount
        db.commit()
        return {"status": "ok", "deleted": deleted}
    finally:
        db.close()
