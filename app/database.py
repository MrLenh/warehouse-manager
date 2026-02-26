from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_add_columns():
    """Add missing columns to existing tables (works for both SQLite and PostgreSQL)."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if "variants" in tables:
        existing = {col["name"] for col in inspector.get_columns("variants")}
        new_cols = {
            "length_in_override": "FLOAT DEFAULT 0.0",
            "width_in_override": "FLOAT DEFAULT 0.0",
            "height_in_override": "FLOAT DEFAULT 0.0",
        }
        with engine.begin() as conn:
            for col_name, col_type in new_cols.items():
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE variants ADD COLUMN {col_name} {col_type}"))

    if "products" in tables:
        existing = {col["name"] for col in inspector.get_columns("products")}
        new_cols = {
            "image_url": "VARCHAR DEFAULT ''",
        }
        with engine.begin() as conn:
            for col_name, col_type in new_cols.items():
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE products ADD COLUMN {col_name} {col_type}"))

    if "orders" in tables:
        existing = {col["name"] for col in inspector.get_columns("orders")}
        new_cols = {
            "order_name": "VARCHAR DEFAULT ''",
            "customer_email": "VARCHAR DEFAULT ''",
            "customer_phone": "VARCHAR DEFAULT ''",
            "carrier": "VARCHAR DEFAULT 'USPS'",
            "service": "VARCHAR DEFAULT 'GroundAdvantage'",
            "ship_to_name": "VARCHAR DEFAULT ''",
            "ship_to_street1": "VARCHAR DEFAULT ''",
            "ship_to_street2": "VARCHAR DEFAULT ''",
            "ship_to_city": "VARCHAR DEFAULT ''",
            "ship_to_state": "VARCHAR DEFAULT ''",
            "ship_to_zip": "VARCHAR DEFAULT ''",
            "ship_to_country": "VARCHAR DEFAULT 'US'",
            "ship_from_name": "VARCHAR DEFAULT 'Warehouse'",
            "ship_from_street1": "VARCHAR DEFAULT ''",
            "ship_from_city": "VARCHAR DEFAULT ''",
            "ship_from_state": "VARCHAR DEFAULT ''",
            "ship_from_zip": "VARCHAR DEFAULT ''",
            "ship_from_country": "VARCHAR DEFAULT 'US'",
            "status_history": "TEXT DEFAULT '[]'",
            "shipping_cost": "FLOAT DEFAULT 0.0",
            "processing_fee": "FLOAT DEFAULT 0.0",
            "total_price": "FLOAT DEFAULT 0.0",
            "easypost_shipment_id": "VARCHAR DEFAULT ''",
            "tracking_number": "VARCHAR DEFAULT ''",
            "tracking_status": "VARCHAR DEFAULT ''",
            "tracking_url": "VARCHAR DEFAULT ''",
            "label_url": "VARCHAR DEFAULT ''",
            "webhook_url": "VARCHAR DEFAULT ''",
            "notes": "TEXT DEFAULT ''",
            "qr_code_path": "VARCHAR DEFAULT ''",
        }
        with engine.begin() as conn:
            for col_name, col_type in new_cols.items():
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}"))

    if "orders" in tables:
        existing = {col["name"] for col in inspector.get_columns("orders")}
        if "invoice_id" not in existing:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE orders ADD COLUMN invoice_id VARCHAR DEFAULT NULL"))

    if "order_items" in tables:
        existing = {col["name"] for col in inspector.get_columns("order_items")}
        new_cols = {
            "variant_id": "VARCHAR DEFAULT ''",
            "variant_sku": "VARCHAR DEFAULT ''",
            "variant_label": "VARCHAR DEFAULT ''",
            "product_name": "VARCHAR DEFAULT ''",
            "unit_price": "FLOAT DEFAULT 0.0",
        }
        with engine.begin() as conn:
            for col_name, col_type in new_cols.items():
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE order_items ADD COLUMN {col_name} {col_type}"))


def _migrate_order_status_enum():
    """Add new enum values to order status (PostgreSQL only)."""
    if not settings.DATABASE_URL.startswith("postgresql"):
        return
    try:
        new_values = [
            ("packing", "processing"),
            ("packed", "packing"),
            ("drop_off", "label_purchased"),
        ]
        with engine.begin() as conn:
            for val, after in new_values:
                result = conn.execute(text(
                    "SELECT 1 FROM pg_enum WHERE enumlabel = :val "
                    "AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'orderstatus')"
                ), {"val": val})
                if not result.fetchone():
                    conn.execute(text(
                        f"ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS '{val}' AFTER '{after}'"
                    ))
    except Exception:
        pass  # SQLite or enum already exists


def init_db():
    # Import all models so Base.metadata knows about them
    import app.models.order  # noqa: F401
    import app.models.product  # noqa: F401
    import app.models.inventory_log  # noqa: F401
    import app.models.stock_request  # noqa: F401
    import app.models.picking  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.customer  # noqa: F401
    import app.models.invoice  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()
    _migrate_order_status_enum()
