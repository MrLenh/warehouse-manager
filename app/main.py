import logging
import pathlib
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

from app.api import auth, orders, picking, products, reports, stock_requests, webhooks
from app.database import init_db
from app.services.auth_service import decode_token, ensure_default_admin

STATIC_DIR = pathlib.Path(__file__).parent / "static"

# Pages that don't require auth
PUBLIC_PATHS = {"/login", "/health", "/api/v1/auth/login", "/api/v1/auth/logout"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Create default admin if no users
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        ensure_default_admin(db)
    finally:
        db.close()
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


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Redirect to /login for page requests if not authenticated."""
    path = request.url.path

    # Allow public paths, static files, API auth endpoints, and health
    if (
        path in PUBLIC_PATHS
        or path.startswith("/static/")
        or path.startswith("/api/v1/auth/")
        or path == "/health"
    ):
        return await call_next(request)

    # For API requests, let the dependency handle auth (returns 401)
    if path.startswith("/api/"):
        return await call_next(request)

    # For page requests, check cookie and redirect to login if missing/invalid
    token = request.cookies.get("token")
    if not token or not decode_token(token):
        return RedirectResponse("/login", status_code=302)

    return await call_next(request)


app.include_router(auth.router, prefix="/api/v1")
app.include_router(products.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(stock_requests.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
app.include_router(picking.router, prefix="/api/v1")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/login")
def login_page():
    return FileResponse(STATIC_DIR / "login.html")


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


@app.get("/packing")
def packing_page():
    """Packing station page for scanning QR codes."""
    return FileResponse(STATIC_DIR / "packing.html")


@app.get("/packing/{picking_list_id}")
def packing_detail_page(picking_list_id: str):
    """Packing station page for a specific picking list."""
    return FileResponse(STATIC_DIR / "packing.html")


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
            "activity_logs",
            "pick_items", "picking_lists",
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
