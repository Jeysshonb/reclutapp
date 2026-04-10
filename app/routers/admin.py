"""
Endpoints de administración: usuarios, catálogos, auditoría.
"""
import os, shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.candidato import (
    CatNegocio, CatCargo, CatFuenteHV, CatResultado,
    CatDepartamento, CatMunicipio, CatMotivoRetiro,
    CatReclutador, CatProveedor,
    Usuario, Auditoria, WaSession, WaArchivo, Candidato,
)
from app.routers.auth import get_current_user, require_role
from app.schemas.candidato import CatalogoCreate, UsuarioCreate, UsuarioUpdate
from app.services.auth import hash_password

router = APIRouter(prefix="/admin", tags=["administración"])

CATALOGOS = {
    "negocio": CatNegocio,
    "cargo": CatCargo,
    "fuente_hv": CatFuenteHV,
    "resultado": CatResultado,
    "departamento": CatDepartamento,
    "municipio": CatMunicipio,
    "motivo_retiro": CatMotivoRetiro,
    "reclutador": CatReclutador,
    "proveedor": CatProveedor,
}


# ── Catálogos ──────────────────────────────────────────────────────────────────

@router.get("/catalogos")
def listar_catalogos_disponibles(_: Usuario = Depends(get_current_user)):
    return list(CATALOGOS.keys())


@router.get("/catalogos/reclutador/desde-candidatos")
def reclutadores_desde_candidatos(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Reclutadores únicos que existen en candidatos reales (incluye Bot WhatsApp)."""
    from sqlalchemy import distinct
    filas = (
        db.query(distinct(Candidato.reclutador))
        .filter(Candidato.deleted_at.is_(None), Candidato.reclutador.isnot(None), Candidato.reclutador != "")
        .order_by(Candidato.reclutador)
        .all()
    )
    nombres = [f[0] for f in filas]
    return [{"id": n, "nombre": n, "activo": True} for n in nombres]


@router.get("/catalogos/{nombre}")
def listar_catalogo(
    nombre: str,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    modelo = CATALOGOS.get(nombre)
    if not modelo:
        raise HTTPException(status_code=404, detail=f"Catálogo '{nombre}' no existe.")
    items = db.query(modelo).order_by(modelo.nombre).all()
    return [{"id": i.id, "nombre": i.nombre, "activo": i.activo} for i in items]


@router.post("/catalogos/{nombre}", status_code=201)
def agregar_catalogo(
    nombre: str,
    body: CatalogoCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador")),
):
    modelo = CATALOGOS.get(nombre)
    if not modelo:
        raise HTTPException(status_code=404, detail=f"Catálogo '{nombre}' no existe.")
    existente = db.query(modelo).filter(modelo.nombre == body.nombre).first()
    if existente:
        existente.activo = True
        db.commit()
        return {"id": existente.id, "nombre": existente.nombre}
    nuevo = modelo(nombre=body.nombre)
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"id": nuevo.id, "nombre": nuevo.nombre}


@router.patch("/catalogos/{nombre}/{item_id}")
def toggle_catalogo(
    nombre: str,
    item_id: int,
    activo: bool,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador")),
):
    modelo = CATALOGOS.get(nombre)
    if not modelo:
        raise HTTPException(status_code=404, detail=f"Catálogo '{nombre}' no existe.")
    item = db.query(modelo).filter(modelo.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado.")
    item.activo = activo
    db.commit()
    return {"id": item.id, "activo": item.activo}


# ── Usuarios ───────────────────────────────────────────────────────────────────

@router.get("/usuarios")
def listar_usuarios(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador")),
):
    usuarios = db.query(Usuario).order_by(Usuario.nombre_display).all()
    return [
        {"id": u.id, "email": u.email, "nombre_display": u.nombre_display,
         "rol": u.rol, "activo": u.activo, "created_at": u.created_at}
        for u in usuarios
    ]


@router.post("/usuarios", status_code=201)
def crear_usuario(
    body: UsuarioCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador")),
):
    if db.query(Usuario).filter(Usuario.email == body.email.lower()).first():
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email.")
    if body.rol not in ("administrador", "especialista", "consulta"):
        raise HTTPException(status_code=400, detail="Rol inválido. Opciones: administrador, especialista, consulta.")
    u = Usuario(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        rol=body.rol,
        nombre_display=body.nombre_display or body.email,
        activo=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id, "email": u.email, "rol": u.rol, "activo": u.activo}


@router.patch("/usuarios/{usuario_id}")
def editar_usuario(
    usuario_id: int,
    body: UsuarioUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador")),
):
    u = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if body.email is not None:
        nuevo_email = body.email.lower().strip()
        if nuevo_email != u.email and db.query(Usuario).filter(Usuario.email == nuevo_email).first():
            raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email.")
        u.email = nuevo_email
    if body.nombre_display is not None:
        u.nombre_display = body.nombre_display
    if body.rol is not None:
        if body.rol not in ("administrador", "especialista", "consulta"):
            raise HTTPException(status_code=400, detail="Rol inválido.")
        u.rol = body.rol
    if body.activo is not None:
        u.activo = body.activo
    if body.password is not None:
        if len(body.password) < 6:
            raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres.")
        u.password_hash = hash_password(body.password)
    db.commit()
    return {"id": u.id, "email": u.email, "rol": u.rol, "activo": u.activo}


# ── Auditoría ──────────────────────────────────────────────────────────────────

@router.get("/auditoria/{candidato_id}")
def ver_auditoria(
    candidato_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador", "especialista")),
):
    registros = db.query(Auditoria).filter(
        Auditoria.candidato_id == candidato_id
    ).order_by(Auditoria.timestamp.desc()).all()
    return [
        {"id": r.id, "accion": r.accion, "detalle": r.detalle,
         "usuario": r.usuario, "timestamp": r.timestamp}
        for r in registros
    ]


@router.get("/wa-sesiones")
def listar_wa_sesiones(
    cedula: str | None = None,
    phone: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador", "especialista")),
):
    import json as _json
    q = db.query(WaSession).order_by(WaSession.updated_at.desc())
    if phone:
        q = q.filter(WaSession.phone == phone)
    sesiones = q.all()
    result = []
    for s in sesiones:
        try:
            data = _json.loads(s.data or '{}')
        except Exception:
            data = {}
        datos = data.get('datos', {})
        s_cedula = datos.get('cedula')
        if cedula and s_cedula != cedula:
            continue
        result.append({
            "phone": s.phone,
            "nombre": datos.get('nombre_completo') or datos.get('nombre'),
            "cedula": s_cedula,
            "step": s.step,
            "data": s.data,
            "updated_at": s.updated_at,
        })
    return result


@router.get("/wa-archivos")
def listar_wa_archivos(
    cedula: str | None = None,
    phone: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador", "especialista")),
):
    q = db.query(WaArchivo).order_by(WaArchivo.created_at.desc())
    if cedula:
        q = q.filter(WaArchivo.cedula == cedula)
    if phone:
        q = q.filter(WaArchivo.phone == phone)
    return [
        {"id": a.id, "phone": a.phone, "cedula": a.cedula, "tipo": a.tipo,
         "nombre": a.nombre, "blob_url": a.blob_url, "created_at": a.created_at}
        for a in q.all()
    ]


@router.post("/upload-db", status_code=200)
async def upload_db(
    request: Request,
    _: Usuario = Depends(require_role("administrador")),
):
    """Sube la BD SQLite como application/octet-stream. Solo admin."""
    from app.database import engine
    try:
        dest = "/home/data/reclutapp.db"
        os.makedirs("/home/data", exist_ok=True)
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="Body vacío")
        # Cerrar todas las conexiones antes de sobreescribir el archivo
        engine.dispose()
        with open(dest, "wb") as f:
            f.write(data)
        size_mb = os.path.getsize(dest) / 1024 / 1024
        return {"ok": True, "size_mb": round(size_mb, 1)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/db-check", tags=["administración"])
def db_check(
    _: Usuario = Depends(require_role("administrador")),
):
    """Verifica columnas de la tabla candidatos y wa_sessions en la BD."""
    from app.database import engine
    import sqlalchemy as sa
    with engine.connect() as conn:
        tablas = {}
        for tabla in ("candidatos", "wa_sessions", "wa_archivos"):
            try:
                rows = conn.execute(sa.text(f"PRAGMA table_info({tabla})")).fetchall()
                tablas[tabla] = [r[1] for r in rows]  # r[1] = nombre columna
            except Exception as e:
                tablas[tabla] = f"ERROR: {e}"
        # Verificar columnas clave
        candidatos_cols = tablas.get("candidatos", [])
        faltantes = [c for c in ("localidad", "zona", "region") if c not in candidatos_cols]
        return {
            "ok": len(faltantes) == 0,
            "columnas_faltantes": faltantes,
            "tablas": tablas,
        }
