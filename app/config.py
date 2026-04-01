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
