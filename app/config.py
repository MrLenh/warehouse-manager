from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Warehouse Manager"
    DATABASE_URL: str = "sqlite:///./warehouse.db"

    EASYPOST_API_KEY: str = ""

    PROCESSING_FEE_PER_ITEM: float = 0.5

    # Default shipping carrier & service
    DEFAULT_CARRIER: str = "USPS"
    DEFAULT_SERVICE: str = "GroundAdvantage"

    # Default warehouse (ship-from) address
    WAREHOUSE_NAME: str = "Warehouse"
    WAREHOUSE_STREET1: str = ""
    WAREHOUSE_CITY: str = ""
    WAREHOUSE_STATE: str = ""
    WAREHOUSE_ZIP: str = ""
    WAREHOUSE_COUNTRY: str = "US"

    # Webhook: list of customer callback URLs (comma-separated)
    WEBHOOK_URLS: str = ""

    # QR code storage
    QR_CODE_DIR: str = "./qrcodes"

    # Base URL for QR code links (set to your domain in production)
    BASE_URL: str = "http://localhost:8000"

    model_config = {"env_file": ".env"}


settings = Settings()
