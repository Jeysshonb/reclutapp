"""
Webhook Meta WhatsApp Cloud API — AraBot producción con número propio.
GET  /api/webhook/meta  → verificación del webhook por Meta
POST /api/webhook/meta  → mensajes entrantes de candidatos
"""
import json
import logging
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, Request, Response, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.candidato import Candidato, WaSession
from app.config import get_settings
from app.routers.whatsapp import _llamar_ia, _guardar_candidato, TIMEOUT_MINUTOS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["whatsapp-meta"])


# ── Enviar mensaje vía Meta Cloud API ─────────────────────────────────────────

async def _enviar_meta(phone: str, texto: str) -> None:
    """Envía un mensaje de texto al número vía Meta Cloud API."""
    s = get_settings()
    if not s.META_ACCESS_TOKEN or not s.META_PHONE_NUMBER_ID:
        logger.error("[Meta] META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
        return
    url = f"https://graph.facebook.com/v19.0/{s.META_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": texto},
    }
    headers = {
        "Authorization": f"Bearer {s.META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code not in (200, 201):
            logger.error(f"[Meta] Error enviando mensaje: {r.status_code} {r.text}")


# ── Verificación del webhook (GET) ────────────────────────────────────────────

@router.get("/meta")
async def meta_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    s = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == s.META_VERIFY_TOKEN:
        logger.info("[Meta] Webhook verificado correctamente")
        return Response(content=hub_challenge, media_type="text/plain")
    logger.warning("[Meta] Verificación de webhook fallida")
    return Response(content="Forbidden", status_code=403)


# ── Mensajes entrantes (POST) ─────────────────────────────────────────────────

@router.post("/meta")
async def meta_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return Response(content="ok", status_code=200)

    # Extraer mensaje del payload de Meta
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return Response(content="ok", status_code=200)

        message = messages[0]
        msg_type = message.get("type", "")

        # Solo procesar mensajes de texto
        if msg_type != "text":
            return Response(content="ok", status_code=200)

        phone = message.get("from", "")   # ej: 573133828176
        msg = message.get("text", {}).get("body", "").strip()

        if not phone or not msg:
            return Response(content="ok", status_code=200)

    except Exception as e:
        logger.error(f"[Meta] Error parseando payload: {e}")
        return Response(content="ok", status_code=200)

    # Procesar con la misma lógica de AraBot
    db = SessionLocal()
    try:
        from app.routers.whatsapp import _get_or_create_session

        session = _get_or_create_session(db, phone)
        state = json.loads(session.data or "{}")
        history = state.get("history", [])
        datos = state.get("datos", {})

        # Detectar timeout de 30 minutos
        ahora = datetime.now(timezone.utc)
        ultima = session.updated_at
        if ultima and ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)

        tiempo_inactivo = (ahora - ultima).total_seconds() / 60 if ultima else 0

        if session.step not in ("done", "activo") and tiempo_inactivo > TIMEOUT_MINUTOS:
            tiene_datos = any(v is not None for v in datos.values())
            if tiene_datos:
                _guardar_candidato(datos, phone, parcial=True)

            history = []
            datos = {}
            session.step = "activo"
            session.data = json.dumps({"history": [], "datos": {}})
            db.commit()

            await _enviar_meta(phone,
                "Hola de nuevo! Soy AraBot de Tiendas Ara.\n\n"
                "Ha pasado un tiempo. Si dejaste un proceso incompleto ya quedo guardado "
                "y un reclutador puede retomarlo contigo.\n\n"
                "Para iniciar un nuevo registro, cuentame tu nombre completo."
            )
            return Response(content="ok", status_code=200)

        if session.step == "done":
            history = []
            datos = {}
            session.step = "activo"
            session.data = json.dumps({"history": [], "datos": {}})
            db.commit()

        # Llamar a la IA
        result = _llamar_ia(history, msg, datos)
        mensaje_bot = result["mensaje"]
        datos_nuevos = result["datos"]
        completo = result.get("completo", False)

        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": mensaje_bot})
        if len(history) > 40:
            history = history[-40:]

        if completo:
            session.step = "done"
            _guardar_candidato(datos_nuevos, phone, parcial=False)
        else:
            session.step = "activo"

        session.data = json.dumps({"history": history, "datos": datos_nuevos}, ensure_ascii=False)
        db.commit()

        await _enviar_meta(phone, mensaje_bot)
        return Response(content="ok", status_code=200)

    except Exception as e:
        logger.error(f"[Meta] Error procesando mensaje: {e}", exc_info=True)
        return Response(content="ok", status_code=200)
    finally:
        db.close()
