import logging
import pathlib
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

from app.api import auth, customers, jobs, orders, picking, portal, products, reports, stock_requests, webhooks
from app.config import settings
from app.database import init_db
from app.services.auth_service import decode_token, ensure_default_admin

STATIC_DIR = pathlib.Path(__file__).parent / "static"

# Pages that don't require auth
PUBLIC_PATHS = {"/login", "/health", "/api/v1/auth/login", "/api/v1/auth/logout"}


def _migrate_uploads():
    """Migrate filesystem images into the database for deploy persistence.

    Handles images from:
    - old app/static/uploads/ directory
    - UPLOAD_DIR (./uploads/)
    Stores image bytes as base64 in Product.image_data and updates image_url
    to the DB-served endpoint /api/v1/products/{id}/image.
    """
    import base64
    import mimetypes

    from app.config import settings
    from app.database import SessionLocal
    from app.models.product import Product

    old_dir = pathlib.Path(__file__).parent / "static" / "uploads"
    upload_dir = pathlib.Path(settings.UPLOAD_DIR)

    db = SessionLocal()
    try:
        # Find products with filesystem-based image_url that haven't been migrated to DB yet
        products = db.query(Product).filter(
            Product.image_url != "",
            Product.image_url.notlike("/api/v1/products/%"),
            (Product.image_data == "") | (Product.image_data.is_(None)),
        ).all()

        migrated = 0
        for p in products:
            # Extract filename from URL like /uploads/X or /static/uploads/X
            filename = p.image_url.split("/")[-1] if "/" in p.image_url else ""
            if not filename:
                continue

            # Try to find the file on disk
            filepath = None
            for search_dir in [upload_dir, old_dir]:
                candidate = search_dir / filename
                if candidate.exists():
                    filepath = candidate
                    break

            if filepath and filepath.exists():
                ext = filepath.suffix.lower()
                content_type = mimetypes.types_map.get(ext, "application/octet-stream")
                p.image_data = base64.b64encode(filepath.read_bytes()).decode("ascii")
                p.image_content_type = content_type
                p.image_url = f"/api/v1/products/{p.id}/image"
                migrated += 1

        if migrated:
            db.commit()
            logger.info("Migrated %d product images from filesystem to database", migrated)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _migrate_uploads()
    # Create default admin if no users
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        ensure_default_admin(db)
    finally:
        db.close()
    # Start background scheduler
    from app.services.scheduler_service import init_scheduler, shutdown_scheduler
    init_scheduler()
    yield
    shutdown_scheduler()


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

    # Allow public paths, static files, uploads, API auth endpoints, and health
    if (
        path in PUBLIC_PATHS
        or path.startswith("/static/")
        or path.startswith("/uploads/")
        or path.startswith("/api/v1/auth/")
        or path.startswith("/picking/")
        or path == "/health"
    ):
        return await call_next(request)

    # Public API: picking list summary (for mobile QR scan)
    if path.startswith("/api/v1/picking-lists/") and path.endswith("/summary"):
        return await call_next(request)

    # For API requests, let the dependency handle auth (returns 401)
    if path.startswith("/api/"):
        return await call_next(request)

    # For page requests, check cookie and redirect to login if missing/invalid
    token = request.cookies.get("token")
    payload = decode_token(token) if token else None
    if not payload:
        return RedirectResponse("/login", status_code=302)

    # Role-based page routing
    from app.database import SessionLocal
    from app.models.user import User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == payload["sub"]).first()
        if user and user.role == "customer":
            # Customer can only access /portal
            if not path.startswith("/portal"):
                return RedirectResponse("/portal", status_code=302)
        elif path.startswith("/portal"):
            # Non-customer users shouldn't access /portal
            return RedirectResponse("/", status_code=302)
    finally:
        db.close()

    return await call_next(request)


app.include_router(auth.router, prefix="/api/v1")
app.include_router(products.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(stock_requests.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
app.include_router(picking.router, prefix="/api/v1")
app.include_router(customers.router, prefix="/api/v1")
app.include_router(portal.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")


# Mount persistent uploads directory (survives deploys)
_upload_dir = pathlib.Path(settings.UPLOAD_DIR)
_upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_upload_dir), name="uploads")

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


@app.get("/portal")
def portal_page():
    """Customer portal — read-only view of own orders, inventory, invoices."""
    return FileResponse(STATIC_DIR / "portal.html")


@app.get("/customers")
def customers_page():
    """Customer & Invoice management page."""
    return FileResponse(STATIC_DIR / "customer.html")


@app.get("/packing")
def packing_page():
    """Packing station page for scanning QR codes."""
    return FileResponse(STATIC_DIR / "packing.html")


@app.get("/packing/{picking_list_id}")
def packing_detail_page(picking_list_id: str):
    """Packing station page for a specific picking list."""
    return FileResponse(STATIC_DIR / "packing.html")


@app.get("/picking/{picking_list_id}")
def picking_summary_page(picking_list_id: str):
    """Mobile-optimized picking summary page — landing for picking list QR scan."""
    return FileResponse(STATIC_DIR / "picking.html")


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
            "invoices",
            "order_items", "orders", "stock_request_boxes", "stock_request_items",
            "stock_requests", "inventory_logs", "variants", "products",
            "customers",
        ]
        deleted = {}
        for tbl in tables:
            result = db.execute(text(f"DELETE FROM {tbl}"))
            deleted[tbl] = result.rowcount
        db.commit()
        return {"status": "ok", "deleted": deleted}
    finally:
        db.close()
