"""
Webhook de Twilio WhatsApp — agente conversacional de reclutamiento.
Recopila datos básicos del candidato y los guarda en la BD.
"""
import json
import logging

from fastapi import APIRouter, Form, Request, Response
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.candidato import Candidato, WaSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["whatsapp"])


# ─────────────────────────────────────────────────────────────────────────────
# Definición del flujo.
# Cada tupla: (step_actual, campo_bd_a_guardar, pregunta_a_enviar, step_siguiente)
#   - campo_bd_a_guardar: nombre del campo de Candidato donde va la respuesta del usuario
#   - pregunta_a_enviar:  texto que se envía al usuario en ESTE paso
#   - step_siguiente:     código del siguiente paso (o "done")
# ─────────────────────────────────────────────────────────────────────────────
PASOS = [
    (
        "start", None,
        "¡Hola! Soy el asistente virtual de reclutamiento de *Tiendas Ara* 🛒\n\n"
        "Voy a recopilar tus datos para el proceso de selección.\n\n"
        "¿Cuál es tu *nombre completo*?",
        "nombre",
    ),
    (
        "nombre", "nombre",
        "Gracias 😊. ¿Cuál es tu número de *cédula de ciudadanía*?",
        "cedula",
    ),
    (
        "cedula", "cedula",
        "¿Cuál es tu *fecha de nacimiento*? (DD/MM/AAAA)",
        "fecha_nac",
    ),
    (
        "fecha_nac", "fecha_nacimiento",
        "¿En qué *ciudad* estás aplicando?",
        "ciudad",
    ),
    (
        "ciudad", "ciudad_aplica",
        "¿A qué *cargo* aspiras?\n\n"
        "Opciones: Operador de Tienda en Formación, Operador de Tienda, "
        "Operador Part Time, Supervisor Junior de Tienda, Supervisor de Tienda, "
        "Jefe de Tienda, Aprendiz SENA",
        "cargo",
    ),
    (
        "cargo", "cargo",
        "¿Cómo te *enteraste* de esta vacante?\n\n"
        "Ej: Computrabajo, Magneto, Indeed, Referido, Redes Sociales, SENA, Feria Laboral",
        "fuente",
    ),
    (
        "fuente", "fuente",
        "¿Cuál es tu *nivel de estudios*?\n\n"
        "Opciones: Bachiller, Técnico, Tecnólogo, Universitario, Posgrado",
        "nivel_ac",
    ),
    (
        "nivel_ac", "nivel_academico",
        "¿Cuál es tu *situación laboral* actual?\n\n"
        "Opciones: Empleado, Desempleado",
        "situacion",
    ),
    (
        "situacion", "situacion_laboral",
        "¿Cuál es tu *aspiración salarial* en pesos colombianos?\n"
        "(escribe solo el número, ej: 1500000)",
        "salario",
    ),
    (
        "salario", "aspiracion_salarial",
        None,   # no hay pregunta; se envía el mensaje de cierre
        "done",
    ),
]

PASO_MAP = {p[0]: p for p in PASOS}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _twiml(text: str) -> Response:
    body = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f"<Response><Message>{text}</Message></Response>"
    )
    return Response(content=body, media_type="application/xml")


def _get_or_create_session(db: Session, phone: str) -> WaSession:
    s = db.query(WaSession).filter(WaSession.phone == phone).first()
    if not s:
        s = WaSession(phone=phone, step="start", data="{}")
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _guardar_candidato(data: dict, phone: str) -> None:
    db = SessionLocal()
    try:
        # Extraer número limpio del formato whatsapp:+57XXXXXXXXX
        tel = phone.replace("whatsapp:", "")

        sal_raw = data.get("aspiracion_salarial", "")
        try:
            salario = float("".join(c for c in str(sal_raw) if c.isdigit() or c == "."))
        except Exception:
            salario = None

        c = Candidato(
            nombre=data.get("nombre", ""),
            cedula=data.get("cedula", "").strip(),
            fecha_nacimiento=data.get("fecha_nacimiento"),
            ciudad_aplica=data.get("ciudad_aplica"),
            cargo=data.get("cargo"),
            fuente=data.get("fuente"),
            nivel_academico=data.get("nivel_academico"),
            situacion_laboral=data.get("situacion_laboral"),
            aspiracion_salarial=salario,
            telefono_contacto=tel,
            reclutador="Bot WhatsApp",
            negocio="Tiendas Ara",
            creado_por="bot_whatsapp",
            status="En Proceso",
        )
        db.add(c)
        db.commit()
        logger.info(f"[WA] Candidato guardado: {c.nombre} / {c.cedula}")
    except Exception as e:
        logger.error(f"[WA] Error guardando candidato: {e}", exc_info=True)
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

    db = SessionLocal()
    try:
        session = _get_or_create_session(db, phone)

        # Si ya terminó y el usuario escribe algo → reiniciar
        if session.step == "done":
            session.step = "start"
            session.data = "{}"
            db.commit()

        step = session.step
        data = json.loads(session.data or "{}")

        paso = PASO_MAP.get(step)
        if not paso:
            # Estado desconocido → reiniciar
            session.step = "start"
            session.data = "{}"
            db.commit()
            paso = PASO_MAP["start"]
            step = "start"
            data = {}

        _, campo_guardar, pregunta, step_siguiente = paso

        # Guardar respuesta del usuario
        if campo_guardar and msg:
            data[campo_guardar] = msg

        # Avanzar estado
        session.step = step_siguiente
        session.data = json.dumps(data, ensure_ascii=False)
        db.commit()

        # ¿Terminamos?
        if step_siguiente == "done":
            _guardar_candidato(data, phone)
            nombre = data.get("nombre", "")
            respuesta = (
                f"✅ ¡Todo listo, {nombre}!\n\n"
                "Tus datos han sido registrados correctamente. "
                "Un reclutador de *Tiendas Ara* se pondrá en contacto contigo pronto. ¡Mucho éxito! 🍀\n\n"
                "_Si deseas iniciar un nuevo registro, escribe cualquier mensaje._"
            )
            return _twiml(respuesta)

        # Enviar la pregunta del paso actual
        return _twiml(pregunta)

    except Exception as e:
        logger.error(f"[WA] Error en webhook: {e}", exc_info=True)
        return _twiml("Ocurrió un error. Por favor intenta de nuevo más tarde.")
    finally:
        db.close()
