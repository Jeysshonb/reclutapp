"""
Webhook de Twilio WhatsApp — agente de IA para reclutamiento de Tiendas Ara.
Usa GPT-4o-mini para mantener conversación natural y extraer datos del candidato.
"""
import json
import logging
from openai import OpenAI

from fastapi import APIRouter, Form, Response
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.candidato import Candidato, WaSession
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["whatsapp"])

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
Eres un asistente virtual de reclutamiento para *Tiendas Ara* (Grupo Jerónimo Martins, Colombia).
Tu misión es recopilar los datos del candidato de forma amable y natural, sin sonar como un formulario.

DATOS QUE DEBES RECOPILAR (en el orden que sea natural, pero todos son necesarios):
1. nombre_completo — nombre completo del candidato
2. cedula — número de cédula (solo dígitos)
3. fecha_nacimiento — formato DD/MM/AAAA
4. ciudad_aplica — ciudad donde aplica al cargo
5. cargo — cargo al que aspira (ej: Operador de Tienda, Supervisor Junior, Aprendiz SENA, etc.)
6. fuente — cómo se enteró de la vacante (Computrabajo, Magneto, Indeed, Referido, Redes Sociales, SENA, Feria Laboral, Voz a Voz, Base de Datos Interna)
7. nivel_academico — nivel de estudios (Bachiller, Técnico, Tecnólogo, Universitario, Posgrado)
8. situacion_laboral — situación actual (Empleado / Desempleado)
9. aspiracion_salarial — número en pesos colombianos (ej: 1500000)

INSTRUCCIONES:
- Saluda al candidato al inicio de forma cálida.
- Haz las preguntas de manera conversacional, puedes hacer varias preguntas en un mismo mensaje si es natural.
- Si el candidato da información sin que se la pidas, extráela y no la vuelvas a pedir.
- Si una respuesta es ambigua, pide aclaración amablemente.
- Si el cargo que menciona no está en la lista estándar de Ara, escríbelo tal como lo dijo.
- Usa emojis moderadamente para parecer amigable.
- Responde SIEMPRE en español colombiano informal pero respetuoso.

FORMATO DE RESPUESTA (CRÍTICO — debes responder SIEMPRE con este JSON exacto, sin markdown, sin explicaciones):
{
  "mensaje": "texto que le envías al candidato",
  "datos": {
    "nombre_completo": null,
    "cedula": null,
    "fecha_nacimiento": null,
    "ciudad_aplica": null,
    "cargo": null,
    "fuente": null,
    "nivel_academico": null,
    "situacion_laboral": null,
    "aspiracion_salarial": null
  },
  "completo": false
}

- En "datos" pon los valores que ya tienes confirmados (null si no los tienes aún).
- Pon "completo": true SOLO cuando tengas los 9 datos confirmados.
- El campo "mensaje" es lo que se le envía al candidato por WhatsApp.
"""


# ── OpenAI client ─────────────────────────────────────────────────────────────

def _get_ai_client():
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        return None
    return OpenAI(api_key=settings.OPENAI_API_KEY)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _twiml(text: str) -> Response:
    # Escapar caracteres XML básicos
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f"<Response><Message>{text}</Message></Response>"
    )
    return Response(content=body, media_type="application/xml")


def _get_or_create_session(db: Session, phone: str) -> WaSession:
    s = db.query(WaSession).filter(WaSession.phone == phone).first()
    if not s:
        s = WaSession(phone=phone, step="activo", data=json.dumps({"history": [], "datos": {}}))
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _llamar_ia(history: list, user_msg: str, datos_actuales: dict) -> dict:
    """
    Llama a GPT-4o-mini con el historial completo.
    Devuelve dict con {mensaje, datos, completo}.
    """
    client = _get_ai_client()
    if not client:
        return {
            "mensaje": "El servicio de IA no está configurado. Contacta al administrador.",
            "datos": datos_actuales,
            "completo": False,
        }

    settings = get_settings()

    # Construir mensajes para la API
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Agregar contexto de datos ya recopilados si los hay
    if any(v is not None for v in datos_actuales.values()):
        ctx = f"Datos ya confirmados hasta ahora: {json.dumps(datos_actuales, ensure_ascii=False)}"
        messages.append({"role": "system", "content": ctx})

    # Historial previo
    messages.extend(history)

    # Mensaje actual del usuario
    messages.append({"role": "user", "content": user_msg})

    try:
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        result = json.loads(raw)

        # Validar estructura mínima
        if "mensaje" not in result:
            result["mensaje"] = "Hubo un problema procesando tu respuesta. ¿Puedes repetirla?"
        if "datos" not in result:
            result["datos"] = datos_actuales
        if "completo" not in result:
            result["completo"] = False

        # Fusionar datos nuevos con existentes (no borrar lo que ya teníamos)
        merged = {**datos_actuales}
        for k, v in result["datos"].items():
            if v is not None:
                merged[k] = v
        result["datos"] = merged

        return result

    except Exception as e:
        logger.error(f"[WA-IA] Error llamando OpenAI: {e}", exc_info=True)
        return {
            "mensaje": "Tuve un problema técnico. Por favor envía tu mensaje de nuevo.",
            "datos": datos_actuales,
            "completo": False,
        }


def _guardar_candidato(datos: dict, phone: str) -> None:
    db = SessionLocal()
    try:
        tel = phone.replace("whatsapp:", "")

        sal_raw = datos.get("aspiracion_salarial") or "0"
        try:
            salario = float("".join(c for c in str(sal_raw) if c.isdigit() or c == "."))
        except Exception:
            salario = None

        c = Candidato(
            nombre=datos.get("nombre_completo", ""),
            cedula=(datos.get("cedula") or "").strip(),
            fecha_nacimiento=datos.get("fecha_nacimiento"),
            ciudad_aplica=datos.get("ciudad_aplica"),
            cargo=datos.get("cargo"),
            fuente=datos.get("fuente"),
            nivel_academico=datos.get("nivel_academico"),
            situacion_laboral=datos.get("situacion_laboral"),
            aspiracion_salarial=salario,
            telefono_contacto=tel,
            reclutador="Bot WhatsApp",
            negocio="Tiendas Ara",
            creado_por="bot_whatsapp",
            status="En Proceso",
        )
        db.add(c)
        db.commit()
        logger.info(f"[WA-IA] Candidato guardado: {c.nombre} / {c.cedula}")
    except Exception as e:
        logger.error(f"[WA-IA] Error guardando candidato: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/whatsapp")
async def whatsapp_webhook(
    From: str = Form(...),
    Body: str = Form(""),
):
    phone = From.strip()
    msg = Body.strip()

    if not msg:
        return _twiml("No recibí tu mensaje. Por favor intenta de nuevo.")

    db = SessionLocal()
    try:
        session = _get_or_create_session(db, phone)
        state = json.loads(session.data or "{}")
        history = state.get("history", [])
        datos = state.get("datos", {})

        # Si ya estaba completo y escribe de nuevo → reiniciar
        if session.step == "done":
            history = []
            datos = {}
            session.step = "activo"

        # Llamar a la IA
        result = _llamar_ia(history, msg, datos)
        mensaje_bot = result["mensaje"]
        datos_nuevos = result["datos"]
        completo = result.get("completo", False)

        # Actualizar historial (guardar los últimos 20 turnos para no inflar el contexto)
        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": mensaje_bot})
        if len(history) > 40:
            history = history[-40:]

        # Guardar estado
        if completo:
            session.step = "done"
            _guardar_candidato(datos_nuevos, phone)
        else:
            session.step = "activo"

        session.data = json.dumps({"history": history, "datos": datos_nuevos}, ensure_ascii=False)
        db.commit()

        return _twiml(mensaje_bot)

    except Exception as e:
        logger.error(f"[WA] Error en webhook: {e}", exc_info=True)
        return _twiml("Ocurrió un error. Por favor intenta de nuevo en un momento.")
    finally:
        db.close()
