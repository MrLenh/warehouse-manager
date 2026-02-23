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
    WAREHOUSE_NAME: str = "Expeditee LLC"
    WAREHOUSE_STREET1: str = "6125 W Sam Houston Pkwy N"
    WAREHOUSE_CITY: str = "Houston"
    WAREHOUSE_STATE: str = "TX"
    WAREHOUSE_ZIP: str = "77041"
    WAREHOUSE_COUNTRY: str = "US"

    # Webhook: list of customer callback URLs (comma-separated)
    WEBHOOK_URLS: str = ""

    # QR code storage
    QR_CODE_DIR: str = "./qrcodes"

    # Base URL for QR code links (set to your domain in production)
    BASE_URL: str = "http://localhost:8000"

    model_config = {"env_file": ".env"}


settings = Settings()
