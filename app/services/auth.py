"""
Funciones de autenticación: hash, verify, JWT.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings
from app.models.candidato import Usuario

settings = get_settings()

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def authenticate_user(db, email: str, password: str):
    user = db.query(Usuario).filter(
        Usuario.email == email.strip().lower(),
        Usuario.activo == True,
    ).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def create_access_token(user: Usuario) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user.id), "rol": user.rol, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Token inválido o expirado: {exc}")
