"""
Configuración de SQLAlchemy + sesión de base de datos.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from app.config import get_settings

settings = get_settings()

# Asegurar que el directorio de la DB exista antes de crear el engine
_db_dir = os.path.dirname(settings.DB_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=settings.APP_ENV == "development",
)


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency de FastAPI para inyectar sesión de DB."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
