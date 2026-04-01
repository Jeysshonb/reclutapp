from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.candidato import Usuario
from app.services.auth import authenticate_user, create_access_token, decode_token, hash_password

router = APIRouter(prefix="/auth", tags=["autenticación"])
bearer = HTTPBearer()
bearer_optional = HTTPBearer(auto_error=False)


# ── Schemas de login ──────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    nombre_display: str
    rol: str


class ChangePasswordRequest(BaseModel):
    password_actual: str
    password_nuevo: str


# ── Dependencia: usuario actual ───────────────────────────────
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(Usuario).filter(
        Usuario.id == int(payload["sub"]),
        Usuario.activo == True,
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado.")
    return user


def get_current_user_download(
    token: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_optional),
    db: Session = Depends(get_db),
) -> Usuario:
    """Igual que get_current_user pero acepta token como query param (para descargas/redirecciones)."""
    raw = token or (credentials.credentials if credentials else None)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    user = db.query(Usuario).filter(Usuario.id == int(payload["sub"]), Usuario.activo == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado.")
    return user


def require_role(*roles: str):
    def _check(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        if current_user.rol not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere uno de los roles: {', '.join(roles)}.",
            )
        return current_user
    return _check


# ── Endpoints ─────────────────────────────────────────────────
@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, body.email.strip().lower(), body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos.",
        )
    return LoginResponse(
        access_token=create_access_token(user),
        nombre_display=user.nombre_display,
        rol=user.rol,
    )


@router.get("/me")
def me(current_user: Usuario = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "nombre_display": current_user.nombre_display,
        "rol": current_user.rol,
    }


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.auth import verify_password
    if not verify_password(body.password_actual, current_user.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta.")
    if len(body.password_nuevo) < 8:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe tener al menos 8 caracteres.")
    current_user.password_hash = hash_password(body.password_nuevo)
    db.commit()
    return {"detail": "Contraseña actualizada correctamente."}


# ── Gestión de usuarios (solo administrador) ──────────────────
class UsuarioCreate(BaseModel):
    email: str
    nombre_display: str
    password: str
    rol: str = "consulta"


@router.post("/usuarios", status_code=201)
def crear_usuario(
    body: UsuarioCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador")),
):
    if body.rol not in ("administrador", "especialista", "consulta"):
        raise HTTPException(status_code=400, detail="Rol inválido. Opciones: administrador, especialista, consulta.")
    existente = db.query(Usuario).filter(Usuario.email == body.email.lower()).first()
    if existente:
        raise HTTPException(status_code=400, detail="El email ya está registrado.")
    nuevo = Usuario(
        email=body.email.strip().lower(),
        nombre_display=body.nombre_display,
        password_hash=hash_password(body.password),
        rol=body.rol,
    )
    db.add(nuevo)
    db.commit()
    return {"id": nuevo.id, "email": nuevo.email, "rol": nuevo.rol}


@router.get("/usuarios")
def listar_usuarios(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador")),
):
    usuarios = db.query(Usuario).order_by(Usuario.nombre_display).all()
    return [
        {"id": u.id, "email": u.email, "nombre_display": u.nombre_display,
         "rol": u.rol, "activo": u.activo}
        for u in usuarios
    ]
