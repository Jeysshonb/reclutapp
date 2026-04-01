"""
CRUD de candidatos — reclutapp.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_
import httpx

from app.database import get_db
from app.models.candidato import Candidato, Auditoria, Usuario
from app.schemas.candidato import CandidatoCreate, CandidatoUpdate, CandidatoOut, CandidatoResumen, HistorialCedula
from app.routers.auth import get_current_user, require_role
from app.config import get_settings

router = APIRouter(prefix="/candidatos", tags=["candidatos"])


def _calcular_imc(peso: Optional[float], altura: Optional[float]):
    if not peso or not altura or altura == 0:
        return None, None
    imc = round(peso / (altura ** 2), 2)
    if imc < 18.5:
        resultado = "Delgado"
    elif imc < 25:
        resultado = "Sano"
    elif imc < 30:
        resultado = "Sobrepeso"
    elif imc < 35:
        resultado = "Sobrepeso Elevado"
    else:
        resultado = "Obesidad"
    return imc, resultado


def _log(db: Session, candidato_id: int, usuario: str, accion: str, detalle: str):
    db.add(Auditoria(candidato_id=candidato_id, usuario=usuario, accion=accion, detalle=detalle))


# ── Consulta historial por cédula (antes de crear) ────────────────────────────

@router.get("/historial/{cedula}", response_model=list[HistorialCedula])
def historial_cedula(
    cedula: str,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """
    Busca todos los procesos anteriores de una cédula.
    Usar antes de registrar un candidato nuevo.
    """
    registros = (
        db.query(Candidato)
        .filter(Candidato.cedula == cedula.strip(), Candidato.deleted_at.is_(None))
        .order_by(Candidato.created_at.desc())
        .all()
    )
    return registros


# ── Estadísticas / KPIs ───────────────────────────────────────────────────────

@router.get("/stats/resumen")
def resumen_stats(
    negocio: Optional[str] = Query(None),
    reclutador: Optional[str] = Query(None),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(Candidato).filter(Candidato.deleted_at.is_(None))
    if negocio:
        q = q.filter(Candidato.negocio == negocio)
    if reclutador:
        q = q.filter(Candidato.reclutador == reclutador)

    todos = q.all()
    total = len(todos)
    contratados = sum(1 for c in todos if (
        (c.tipo_status and c.tipo_status.lower() == "contratado") or
        c.fecha_contratacion is not None
    ))
    aptos_op = sum(1 for c in todos if c.resultado_operaciones and
                   c.resultado_operaciones.upper() in ("APTO", "APTO CON RESTRICCION"))
    no_aptos = sum(1 for c in todos if (
        (c.tipo_status and "no apto" in c.tipo_status.lower()) or
        (c.resultado_operaciones and "no apto" in c.resultado_operaciones.lower())
    ))
    lista_negra = sum(1 for c in todos if c.lista_negra)
    en_proceso = sum(1 for c in todos if c.status and c.status.lower() == "en proceso")

    return {
        "total": total,
        "contratados": contratados,
        "aptos_operaciones": aptos_op,
        "no_aptos": no_aptos,
        "en_proceso": en_proceso,
        "lista_negra": lista_negra,
    }


# ── Listar candidatos ─────────────────────────────────────────────────────────

@router.get("/", response_model=dict)
def listar_candidatos(
    negocio: Optional[str] = Query(None),
    reclutador: Optional[str] = Query(None),
    cargo: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    resultado_operaciones: Optional[str] = Query(None),
    lista_negra: Optional[bool] = Query(None),
    buscar: Optional[str] = Query(None, description="Busca por nombre o cédula"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(Candidato).filter(Candidato.deleted_at.is_(None))

    if negocio:
        q = q.filter(Candidato.negocio == negocio)
    if reclutador:
        q = q.filter(Candidato.reclutador == reclutador)
    if cargo:
        q = q.filter(Candidato.cargo == cargo)
    if status:
        q = q.filter(
            (Candidato.status == status) |
            (Candidato.tipo_status == status) |
            (Candidato.tipo_status.ilike(status))
        )
    if resultado_operaciones:
        q = q.filter(Candidato.resultado_operaciones.ilike(resultado_operaciones))
    if lista_negra is not None:
        q = q.filter(Candidato.lista_negra == lista_negra)
    if buscar:
        term = f"%{buscar}%"
        q = q.filter(or_(Candidato.nombre.ilike(term), Candidato.cedula.ilike(term)))

    total = q.count()
    candidatos = q.order_by(Candidato.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": [CandidatoResumen.model_validate(c) for c in candidatos]}


# ── Obtener uno ───────────────────────────────────────────────────────────────

@router.get("/{candidato_id}", response_model=CandidatoOut)
def obtener_candidato(
    candidato_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    c = db.query(Candidato).filter(
        Candidato.id == candidato_id, Candidato.deleted_at.is_(None)
    ).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")
    return c


# ── Crear candidato ───────────────────────────────────────────────────────────

@router.post("/", response_model=CandidatoOut, status_code=201)
def crear_candidato(
    body: CandidatoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role("administrador", "especialista")),
):
    imc, resultado_imc = _calcular_imc(body.peso, body.altura)
    data = body.model_dump()
    data["imc"] = imc
    data["resultado_imc"] = resultado_imc
    data["creado_por"] = current_user.email
    data["actualizado_por"] = current_user.email

    candidato = Candidato(**data)
    db.add(candidato)
    db.commit()
    db.refresh(candidato)
    _log(db, candidato.id, current_user.email, "CREATE",
         f"Candidato {candidato.nombre} (CC {candidato.cedula}) creado.")
    db.commit()
    return candidato


# ── Editar candidato ──────────────────────────────────────────────────────────

@router.put("/{candidato_id}", response_model=CandidatoOut)
def editar_candidato(
    candidato_id: int,
    body: CandidatoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role("administrador", "especialista")),
):
    candidato = db.query(Candidato).filter(
        Candidato.id == candidato_id, Candidato.deleted_at.is_(None)
    ).first()
    if not candidato:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")

    cambios = []
    data = body.model_dump(exclude_unset=True)

    # Recalcular IMC si cambian peso o altura
    nuevo_peso = data.get("peso", candidato.peso)
    nueva_altura = data.get("altura", candidato.altura)
    if "peso" in data or "altura" in data:
        imc, resultado_imc = _calcular_imc(nuevo_peso, nueva_altura)
        data["imc"] = imc
        data["resultado_imc"] = resultado_imc

    for campo, valor in data.items():
        valor_anterior = getattr(candidato, campo, None)
        if valor_anterior != valor:
            cambios.append(f"{campo}: '{valor_anterior}' → '{valor}'")
            setattr(candidato, campo, valor)

    candidato.actualizado_por = current_user.email
    db.commit()
    db.refresh(candidato)

    if cambios:
        _log(db, candidato.id, current_user.email, "UPDATE", " | ".join(cambios))
        db.commit()

    return candidato


# ── Eliminar (soft delete, solo admin) ───────────────────────────────────────

@router.delete("/{candidato_id}", status_code=204)
def eliminar_candidato(
    candidato_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role("administrador")),
):
    from datetime import datetime
    candidato = db.query(Candidato).filter(
        Candidato.id == candidato_id, Candidato.deleted_at.is_(None)
    ).first()
    if not candidato:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")
    candidato.deleted_at = datetime.utcnow()
    candidato.actualizado_por = current_user.email
    db.commit()
    _log(db, candidato.id, current_user.email, "DELETE",
         f"Candidato {candidato.nombre} eliminado (soft delete).")
    db.commit()


# ── Enviar SMS (Hablame.co) ───────────────────────────────────────────────────

class SmsRequest(BaseModel):
    telefono: str
    mensaje: str


@router.post("/enviar-sms", tags=["sms"])
async def enviar_sms(
    body: SmsRequest,
    current_user: Usuario = Depends(get_current_user),
):
    settings = get_settings()
    if not settings.HABLAME_API_KEY:
        raise HTTPException(status_code=503, detail="SMS no configurado.")

    # Normalizar número: quitar todo excepto dígitos y agregar 57 si es colombiano
    digits = "".join(c for c in body.telefono if c.isdigit())
    if digits.startswith("57") and len(digits) >= 11:
        numero = digits
    elif len(digits) == 10:
        numero = "57" + digits
    else:
        raise HTTPException(status_code=400, detail=f"Número inválido: {body.telefono}")

    payload = {
        "messages": [{"to": numero, "text": body.mensaje}],
        "priority": False,
        "flash": False,
    }
    headers = {
        "Content-Type": "application/json",
        "accept": "application/json",
        "X-Hablame-Key": settings.HABLAME_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as client:
            r = await client.post(settings.HABLAME_API_URL, json=payload, headers=headers)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Hablame error {r.status_code}: {data}")
        return {"ok": True, "numero": numero, "respuesta": data}
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Error de red al enviar SMS: {e}")
