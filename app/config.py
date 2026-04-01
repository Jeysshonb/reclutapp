from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_NAME: str = "reclutapp"
    APP_VERSION: str = "1.0.0"
    SECRET_KEY: str = "cambia-esto-en-produccion-minimo32chars!"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480   # 8 horas de sesión

    # SQLite: ruta al archivo de base de datos
    # En Azure usa /home/data/ (persistente); en local usa ./data/
    DB_PATH: str = "data/reclutapp.db"

    ALLOWED_ORIGINS: str = "http://localhost:8000"

    # Hablame.co SMS
    HABLAME_API_URL: str = "https://www.hablame.co/api/sms/v5/send"
    HABLAME_ACCOUNT: str = ""
    HABLAME_API_KEY: str = ""

    # Azure Blob Storage (opcional, configurar cuando esté listo)
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    AZURE_BLOB_CONTAINER: str = "reclutapp-archivos"

    # Twilio WhatsApp
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str = ""       # https://xxx.openai.azure.com/
    AZURE_OPENAI_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-4o-mini"
    AZURE_OPENAI_API_VERSION: str = "2024-08-01-preview"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.DB_PATH}"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
