from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Warehouse Manager"
    DATABASE_URL: str = "sqlite:///./warehouse.db"

    EASYPOST_API_KEY: str = ""

    PROCESSING_FEE_PER_ITEM: float = 0.5

    # Webhook: list of customer callback URLs (comma-separated)
    WEBHOOK_URLS: str = ""

    # QR code storage
    QR_CODE_DIR: str = "./qrcodes"

    model_config = {"env_file": ".env"}


settings = Settings()
