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
    """Add missing columns to existing tables (for SQLite without Alembic)."""
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

    if "orders" in tables:
        existing = {col["name"] for col in inspector.get_columns("orders")}
        new_cols = {
            "qr_code_path": "VARCHAR DEFAULT ''",
        }
        with engine.begin() as conn:
            for col_name, col_type in new_cols.items():
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}"))


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()
