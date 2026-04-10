"""
Servicio de almacenamiento de archivos.
- Azure Blob Storage si AZURE_STORAGE_CONNECTION_STRING está configurado.
- Almacenamiento local en data/uploads/ como fallback (desarrollo).
"""
import logging
import mimetypes
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_client = None
_container = None
_local_dir: Optional[str] = None   # ruta absoluta a data/uploads/ cuando no hay Azure


# ── Inicialización ─────────────────────────────────────────────────────────────

def init_blob(connection_string: str, container_name: str):
    global _client, _container
    if not connection_string:
        logger.warning("Azure Blob no configurado (AZURE_STORAGE_CONNECTION_STRING vacío)")
        return
    try:
        from azure.storage.blob import BlobServiceClient
        service = BlobServiceClient.from_connection_string(connection_string)
        container_client = service.get_container_client(container_name)
        try:
            container_client.create_container()
        except Exception:
            pass
        _client = service
        _container = container_name
        logger.info(f"Azure Blob iniciado — contenedor: {container_name}")
    except ImportError:
        logger.error("Paquete azure-storage-blob no instalado")
    except Exception as e:
        logger.error(f"Error iniciando Azure Blob: {e}")


def init_local(uploads_path: str):
    """Activa modo de almacenamiento local."""
    global _local_dir
    os.makedirs(uploads_path, exist_ok=True)
    _local_dir = uploads_path
    logger.info(f"Almacenamiento local activado: {uploads_path}")


def is_available() -> bool:
    # Lazy init Azure si hay variable de entorno
    global _client, _container
    if _client is None and _local_dir is None:
        conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        cont = os.environ.get("AZURE_BLOB_CONTAINER", "reclutapp-archivos")
        if conn:
            try:
                from azure.storage.blob import BlobServiceClient
                _client = BlobServiceClient.from_connection_string(conn)
                _container = cont
            except Exception as e:
                logger.error(f"Error lazy init Azure Blob: {e}")
    return _client is not None or _local_dir is not None


# ── Operaciones ────────────────────────────────────────────────────────────────

def upload_file(file_bytes: bytes, original_filename: str, candidato_id: int) -> dict:
    if not is_available():
        raise RuntimeError("Almacenamiento no configurado")

    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "bin"
    tipo = _detectar_tipo(ext)
    uid = uuid.uuid4().hex

    # ── Azure ──
    if _client is not None:
        blob_name = f"candidato-{candidato_id}/{uid}.{ext}"
        mime, _ = mimetypes.guess_type(original_filename)
        content_type = mime or "application/octet-stream"
        blob_client = _client.get_blob_client(container=_container, blob=blob_name)
        blob_client.upload_blob(
            file_bytes, overwrite=True,
            content_settings=_make_content_settings(content_type),
        )
        sas_url = generate_sas_url(blob_name, hours=365 * 24 * 5)  # 5 años
        return {"blob_name": blob_name, "blob_url": sas_url or blob_client.url, "tipo": tipo}

    # ── Local ──
    folder = os.path.join(_local_dir, f"candidato-{candidato_id}")
    os.makedirs(folder, exist_ok=True)
    filename = f"{uid}.{ext}"
    local_path = os.path.join(folder, filename)
    with open(local_path, "wb") as f:
        f.write(file_bytes)
    blob_name = f"candidato-{candidato_id}/{filename}"
    blob_url = f"/uploads/{blob_name}"
    return {"blob_name": blob_name, "blob_url": blob_url, "tipo": tipo}


def download_blob(blob_name: str):
    if _client is not None:
        try:
            blob_client = _client.get_blob_client(container=_container, blob=blob_name)
            props = blob_client.get_blob_properties()
            ct = props.content_settings.content_type or "application/octet-stream"
            data = blob_client.download_blob().readall()
            return data, ct
        except Exception as e:
            logger.error(f"Error descargando blob {blob_name}: {e}")
            return None, None

    if _local_dir is not None:
        local_path = os.path.join(_local_dir, blob_name)
        if os.path.isfile(local_path):
            mime, _ = mimetypes.guess_type(local_path)
            with open(local_path, "rb") as f:
                return f.read(), mime or "application/octet-stream"
    return None, None


def delete_file(blob_name: str):
    if _client is not None:
        try:
            _client.get_blob_client(container=_container, blob=blob_name).delete_blob()
        except Exception as e:
            logger.error(f"Error eliminando blob {blob_name}: {e}")
        return

    if _local_dir is not None:
        local_path = os.path.join(_local_dir, blob_name)
        if os.path.isfile(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                logger.error(f"Error eliminando archivo local {local_path}: {e}")


def generate_sas_url_for(container_name: str, blob_name: str, hours: int = 4) -> str:
    """Genera SAS URL para cualquier contenedor de la misma cuenta."""
    is_available()
    if _client is None:
        return ""
    try:
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions
        from datetime import datetime, timedelta, timezone
        account_name = _client.account_name
        account_key = getattr(_client.credential, "account_key", None)
        if not account_key:
            return ""
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=container_name,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=hours),
        )
        return f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}?{sas}"
    except Exception as e:
        logger.error(f"Error generando SAS URL ({container_name}/{blob_name}): {e}", exc_info=True)
        return ""


def _refresh_wa_url(blob_url: str, hours: int = 4) -> str:
    """Si la URL de WaArchivo no tiene SAS, extrae el blob_name y regenera SAS."""
    if not blob_url:
        return blob_url
    # Si ya tiene SAS token, devolver tal cual
    if "?se=" in blob_url or "?sv=" in blob_url or "&sig=" in blob_url:
        return blob_url
    # Extraer container y blob_name de la URL directa
    # Formato: https://{account}.blob.core.windows.net/{container}/{blob_name}
    try:
        from urllib.parse import urlparse
        parsed = urlparse(blob_url)
        parts = parsed.path.lstrip("/").split("/", 1)
        if len(parts) == 2:
            container_name, blob_name = parts
            sas_url = generate_sas_url_for(container_name, blob_name, hours=hours)
            return sas_url or blob_url
    except Exception:
        pass
    return blob_url


def generate_sas_url(blob_name: str, hours: int = 2) -> str:
    # Asegurar lazy init
    is_available()
    if _client is None:
        if _local_dir is not None:
            return f"/uploads/{blob_name}"
        return ""
    try:
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions
        from datetime import datetime, timedelta, timezone
        account_name = _client.account_name
        cred = _client.credential
        # StorageSharedKeyCredential expone account_key
        account_key = getattr(cred, "account_key", None)
        if not account_key:
            # Intentar extraer desde named_key_credential
            account_key = getattr(cred, "named_key", {}).get("key") if hasattr(cred, "named_key") else None
        if not account_key:
            logger.error("No se puede generar SAS: account_key no disponible en la credencial")
            return ""
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=_container,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=hours),
        )
        return f"https://{account_name}.blob.core.windows.net/{_container}/{blob_name}?{sas}"
    except Exception as e:
        logger.error(f"Error generando SAS URL: {e}", exc_info=True)
        return ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _detectar_tipo(ext: str) -> str:
    if ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
        return "foto"
    if ext in ("mp4", "avi", "mov", "mkv", "webm"):
        return "video"
    if ext == "pdf":
        return "pdf"
    return "otro"


def _make_content_settings(content_type: str):
    try:
        from azure.storage.blob import ContentSettings
        return ContentSettings(content_type=content_type)
    except ImportError:
        return None
