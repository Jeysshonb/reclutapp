"""
Gestión de archivos adjuntos a candidatos (Azure Blob Storage).
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.candidato import Candidato, ArchivoCandidato, Usuario
from app.routers.auth import get_current_user, get_current_user_download, require_role
from app.services import blob_service

router = APIRouter(prefix="/archivos", tags=["archivos"])

MAX_SIZE_MB = 50
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024


@router.post("/{candidato_id}")
async def subir_archivo(
    candidato_id: int,
    archivo: UploadFile = File(...),
    etapa: str = Form("general"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role("administrador", "especialista")),
):
    c = db.query(Candidato).filter(
        Candidato.id == candidato_id, Candidato.deleted_at.is_(None)
    ).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")

    if not blob_service.is_available():
        raise HTTPException(
            status_code=503,
            detail="Azure Blob Storage no está configurado. Configura la conexión primero.",
        )

    contenido = await archivo.read()
    if len(contenido) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"El archivo supera el límite de {MAX_SIZE_MB} MB.")

    try:
        resultado = blob_service.upload_file(contenido, archivo.filename, candidato_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir archivo: {e}")

    etapa_val = etapa if etapa in ("operaciones","rrhh","emo","es","contratacion","general") else "general"
    nuevo = ArchivoCandidato(
        candidato_id=candidato_id,
        nombre_original=archivo.filename,
        blob_name=resultado["blob_name"],
        blob_url=resultado["blob_url"],
        tipo=resultado["tipo"],
        tamanio_bytes=len(contenido),
        etapa=etapa_val,
        subido_por_id=current_user.id,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {
        "id": nuevo.id,
        "nombre_original": nuevo.nombre_original,
        "blob_url": nuevo.blob_url,
        "tipo": nuevo.tipo,
        "tamanio_bytes": nuevo.tamanio_bytes,
    }


@router.delete("/{archivo_id}", status_code=204)
def eliminar_archivo(
    archivo_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role("administrador", "especialista")),
):
    arch = db.query(ArchivoCandidato).filter(ArchivoCandidato.id == archivo_id).first()
    if not arch:
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    blob_service.delete_file(arch.blob_name)
    db.delete(arch)
    db.commit()


@router.get("/view/{archivo_id}")
def ver_archivo(
    archivo_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user_download),
):
    from fastapi.responses import Response
    arch = db.query(ArchivoCandidato).filter(ArchivoCandidato.id == archivo_id).first()
    if not arch:
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    if not blob_service.is_available():
        raise HTTPException(status_code=503, detail="Azure Blob Storage no configurado.")
    data, content_type = blob_service.download_blob(arch.blob_name)
    if data is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado en el storage.")
    headers = {"Content-Disposition": f'inline; filename="{arch.nombre_original}"'}
    return Response(content=data, media_type=content_type, headers=headers)


@router.get("/{candidato_id}")
def listar_archivos(
    candidato_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    archivos = db.query(ArchivoCandidato).filter(
        ArchivoCandidato.candidato_id == candidato_id
    ).order_by(ArchivoCandidato.created_at).all()
    return [
        {"id": a.id, "nombre_original": a.nombre_original, "blob_url": a.blob_url,
         "tipo": a.tipo, "tamanio_bytes": a.tamanio_bytes,
         "etapa": a.etapa or "general", "created_at": str(a.created_at)}
        for a in archivos
    ]
