"""
Webhook de Twilio WhatsApp — AraBot, agente IA de reclutamiento Tiendas Ara.
- Recoge datos personales, laborales y de experiencia del candidato.
- Guarda datos parciales si el candidato abandona > 30 minutos.
- Retoma la conversación si el candidato vuelve a escribir.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from openai import AzureOpenAI

from fastapi import APIRouter, Form, Response
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.candidato import Candidato, WaSession
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["whatsapp"])

TIMEOUT_MINUTOS = 30

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
Eres *AraBot*, el asistente virtual de reclutamiento de *Tiendas Ara* (Grupo Jerónimo Martins, Colombia).
Tienes 50 años de experiencia en selección de personal operativo en retail colombiano.
Eres cálido, directo, profesional y conoces perfectamente los perfiles que busca Ara.

TU MISIÓN: Entrevistar al candidato por WhatsApp y recopilar sus datos de forma natural y amigable.
Habla como un reclutador experto de verdad — no como un formulario. Puedes combinar varias preguntas
en un mensaje cuando sea natural. Si el candidato da información sin que se la pidas, captúrala.

DATOS QUE DEBES RECOPILAR (en el orden que fluya mejor):

DATOS PERSONALES:
- nombre_completo: nombre completo
- cedula: número de cédula (solo dígitos)
- fecha_nacimiento: DD/MM/AAAA
- genero: Masculino / Femenino / Otro
- correo: correo electrónico
- ciudad_aplica: ciudad donde aplica
- departamento: departamento de Colombia donde vive

DATOS LABORALES:
- cargo: cargo al que aspira (opciones: Operador de Tienda en Formación, Operador de Tienda,
  Operador de Tienda y Montacarga, Operador Part Time, Supervisor Junior de Tienda,
  Supervisor de Tienda, Jefe de Tienda, Aprendiz SENA)
- fuente: cómo se enteró (Computrabajo, Magneto, Indeed, SENA, Referido, Redes Sociales,
  Feria Laboral, Voz a Voz, Base de Datos Interna)
- nivel_academico: Bachiller / Técnico / Tecnólogo / Universitario / Posgrado
- situacion_laboral: Empleado / Desempleado
- aspiracion_salarial: número en pesos colombianos (ej: 1350000)

FAMILIA Y DISPONIBILIDAD:
- tiene_hijos: Sí / No
- disponibilidad_desplazamiento: ¿está dispuesto a desplazarse a otras ciudades? Sí / No

EXPERIENCIA PREVIA (solo la más reciente, si tiene):
- exp1_empresa: nombre de la empresa anterior (o "Sin experiencia")
- exp1_cargo: cargo que desempeñó
- exp1_tiempo: cuánto tiempo trabajó ahí (ej: "2 años", "6 meses")

REGLAS:
- Habla en español colombiano natural, cálido y profesional.
- Usa máximo 1-2 emojis por mensaje.
- Si algo no queda claro, pide amablemente que repita.
- Si el candidato pregunta algo sobre Ara o el proceso, respóndele brevemente antes de continuar.
- Para experiencia, si dice que no tiene, acepta "Sin experiencia" en los 3 campos de exp.
- NUNCA inventes datos que el candidato no haya dado.
- Cuando tengas los 17 datos, despídete indicando que un reclutador lo contactará pronto.

FORMATO DE RESPUESTA — SIEMPRE responde con este JSON exacto (sin markdown, sin texto extra):
{
  "mensaje": "texto que le envías al candidato",
  "datos": {
    "nombre_completo": null,
    "cedula": null,
    "fecha_nacimiento": null,
    "genero": null,
    "correo": null,
    "ciudad_aplica": null,
    "departamento": null,
    "cargo": null,
    "fuente": null,
    "nivel_academico": null,
    "situacion_laboral": null,
    "aspiracion_salarial": null,
    "tiene_hijos": null,
    "disponibilidad_desplazamiento": null,
    "exp1_empresa": null,
    "exp1_cargo": null,
    "exp1_tiempo": null
  },
  "completo": false
}

- En "datos" pon los valores confirmados (null si aún no los tienes).
- "completo": true SOLO cuando los 17 campos tengan valor (no null).
- "mensaje" es exactamente lo que se envía por WhatsApp.
"""


# ── Cliente Azure OpenAI ──────────────────────────────────────────────────────

def _get_client():
    s = get_settings()
    if not s.AZURE_OPENAI_ENDPOINT or not s.AZURE_OPENAI_KEY:
        return None
    return AzureOpenAI(
        azure_endpoint=s.AZURE_OPENAI_ENDPOINT,
        api_key=s.AZURE_OPENAI_KEY,
        api_version=s.AZURE_OPENAI_API_VERSION,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _twiml(text: str) -> Response:
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Response(
        content=f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{safe}</Message></Response>",
        media_type="application/xml",
    )


def _get_or_create_session(db: Session, phone: str) -> WaSession:
    s = db.query(WaSession).filter(WaSession.phone == phone).first()
    if not s:
        s = WaSession(phone=phone, step="activo", data=json.dumps({"history": [], "datos": {}}))
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _llamar_ia(history: list, user_msg: str, datos: dict, nombre: str | None = None) -> dict:
    client = _get_client()
    if not client:
        return {"mensaje": "Servicio de IA no configurado.", "datos": datos, "completo": False}

    s = get_settings()
    system = SYSTEM_PROMPT
    if nombre:
        system += f"\n\nEl candidato se llama '{nombre}' según su perfil de WhatsApp. Salúdalo por su nombre en el primer mensaje."
    messages = [{"role": "system", "content": system}]
    if any(v is not None for v in datos.values()):
        messages.append({
            "role": "system",
            "content": f"Datos confirmados hasta ahora: {json.dumps(datos, ensure_ascii=False)}"
        })
    messages.extend(history)
    messages.append({"role": "user", "content": user_msg})

    try:
        resp = client.chat.completions.create(
            model=s.AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0.4,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        if "mensaje" not in result:
            result["mensaje"] = "Hubo un problema. ¿Puedes repetir tu respuesta?"
        if "datos" not in result:
            result["datos"] = datos
        if "completo" not in result:
            result["completo"] = False
        # Fusionar: no borrar datos ya confirmados
        merged = {**datos}
        for k, v in result["datos"].items():
            if v is not None:
                merged[k] = v
        result["datos"] = merged
        return result
    except Exception as e:
        logger.error(f"[AraBot] Error OpenAI: {e}", exc_info=True)
        return {"mensaje": "Tuve un problema técnico. Por favor envía tu mensaje de nuevo.", "datos": datos, "completo": False}


def _guardar_candidato(datos: dict, phone: str, parcial: bool = False) -> None:
    db = SessionLocal()
    try:
        tel = phone.replace("whatsapp:", "")

        sal_raw = datos.get("aspiracion_salarial") or "0"
        try:
            salario = float("".join(c for c in str(sal_raw) if c.isdigit() or c == "."))
        except Exception:
            salario = None

        tiene_hijos_raw = datos.get("tiene_hijos", "")
        tiene_hijos = str(tiene_hijos_raw).lower() in ("sí", "si", "s", "true", "1")

        disp_raw = datos.get("disponibilidad_desplazamiento", "")
        disponibilidad = str(disp_raw).lower() in ("sí", "si", "s", "true", "1")

        status = "Incompleto - Bot WA" if parcial else "En Proceso"
        obs = f"[{'Registro parcial' if parcial else 'Registro completo'} por AraBot vía WhatsApp]\nNúmero WA: {tel}"

        # Tiempo de experiencia va en funciones si no hay campo directo
        exp_funciones = datos.get("exp1_tiempo")

        c = Candidato(
            nombre=datos.get("nombre_completo", ""),
            cedula=(datos.get("cedula") or "").strip(),
            fecha_nacimiento=datos.get("fecha_nacimiento"),
            genero=datos.get("genero"),
            correo=datos.get("correo"),
            ciudad_aplica=datos.get("ciudad_aplica"),
            departamento=datos.get("departamento"),
            cargo=datos.get("cargo"),
            fuente=datos.get("fuente"),
            nivel_academico=datos.get("nivel_academico"),
            situacion_laboral=datos.get("situacion_laboral"),
            aspiracion_salarial=salario,
            tiene_hijos=tiene_hijos,
            disponibilidad_desplazamiento=disponibilidad,
            exp1_empresa=datos.get("exp1_empresa"),
            exp1_cargo=datos.get("exp1_cargo"),
            exp1_funciones=exp_funciones,
            telefono_contacto=tel,
            reclutador="Bot WhatsApp",
            creado_por=f"bot_whatsapp | {tel}",
            observaciones_analistas=obs,
            negocio="Tiendas Ara",
            status=status,
        )
        db.add(c)
        db.commit()
        logger.info(f"[AraBot] Candidato {'parcial' if parcial else 'completo'} guardado: {c.nombre} / {tel}")
    except Exception as e:
        logger.error(f"[AraBot] Error guardando candidato: {e}", exc_info=True)
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

        # ── Detectar abandono por timeout ─────────────────────────────────────
        ahora = datetime.now(timezone.utc)
        ultima = session.updated_at
        if ultima and ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)

        tiempo_inactivo = (ahora - ultima).total_seconds() / 60 if ultima else 0

        if session.step not in ("done", "activo_nuevo") and tiempo_inactivo > TIMEOUT_MINUTOS:
            # Si tenía datos a medias → guardar como parcial
            tiene_datos = any(v is not None for v in datos.values())
            if tiene_datos and session.step != "start":
                _guardar_candidato(datos, phone, parcial=True)
                logger.info(f"[AraBot] Guardado parcial por timeout ({tiempo_inactivo:.0f} min): {phone}")

            # Reiniciar sesión
            history = []
            datos = {}
            session.step = "activo"
            session.data = json.dumps({"history": [], "datos": {}})
            db.commit()

            bienvenida = (
                "¡Hola de nuevo! 👋 Soy AraBot de Tiendas Ara.\n\n"
                "Ha pasado un tiempo desde tu última sesión. "
                "Si dejaste un proceso incompleto, ya quedó guardado y un reclutador puede retomarlo contigo.\n\n"
                "¿Quieres iniciar un nuevo registro? Cuéntame tu nombre completo."
            )
            return _twiml(bienvenida)

        # ── Si ya terminó y vuelve a escribir → reiniciar ────────────────────
        if session.step == "done":
            history = []
            datos = {}
            session.step = "activo"
            session.data = json.dumps({"history": [], "datos": {}})
            db.commit()

        # ── Llamar a la IA ────────────────────────────────────────────────────
        result = _llamar_ia(history, msg, datos)
        mensaje_bot = result["mensaje"]
        datos_nuevos = result["datos"]
        completo = result.get("completo", False)

        # Actualizar historial (máx 40 turnos)
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

        return _twiml(mensaje_bot)

    except Exception as e:
        logger.error(f"[AraBot] Error en webhook: {e}", exc_info=True)
        return _twiml("Ocurrió un error. Por favor intenta de nuevo en un momento.")
    finally:
        db.close()


# ── Endpoint JSON para whatsapp-web.js (Node.js) ──────────────────────────────

from fastapi import Body as FBody
from pydantic import BaseModel

class WaMensaje(BaseModel):
    phone: str
    message: str
    nombre: str | None = None

@router.post("/whatsapp/json")
async def whatsapp_json(payload: WaMensaje):
    """Endpoint para el bot Node.js (whatsapp-web.js). Recibe JSON, devuelve JSON."""
    phone = payload.phone.strip()
    msg = payload.message.strip()

    if not msg:
        return {"response": "No recibí tu mensaje. Por favor intenta de nuevo."}

    db = SessionLocal()
    try:
        session = _get_or_create_session(db, phone)
        state = json.loads(session.data or "{}")
        history = state.get("history", [])
        datos = state.get("datos", {})

        ahora = datetime.now(timezone.utc)
        ultima = session.updated_at
        if ultima and ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        tiempo_inactivo = (ahora - ultima).total_seconds() / 60 if ultima else 0

        if session.step not in ("done", "activo") and tiempo_inactivo > TIMEOUT_MINUTOS:
            tiene_datos = any(v is not None for v in datos.values())
            if tiene_datos:
                _guardar_candidato(datos, phone, parcial=True)
            history, datos = [], {}
            session.step = "activo"
            session.data = json.dumps({"history": [], "datos": {}})
            db.commit()
            return {"response": (
                "Hola de nuevo! Soy AraBot de Tiendas Ara.\n\n"
                "Ha pasado un tiempo. Si dejaste un proceso incompleto ya quedo guardado.\n\n"
                "Para iniciar un nuevo registro, cuentame tu nombre completo."
            )}

        if session.step == "done":
            history, datos = [], {}
            session.step = "activo"
            session.data = json.dumps({"history": [], "datos": {}})
            db.commit()

        result = _llamar_ia(history, msg, datos, nombre=payload.nombre)
        mensaje_bot = result["mensaje"]
        datos_nuevos = result["datos"]
        completo = result.get("completo", False)

        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": mensaje_bot})
        if len(history) > 40:
            history = history[-40:]

        session.step = "done" if completo else "activo"
        if completo:
            _guardar_candidato(datos_nuevos, phone, parcial=False)
        session.data = json.dumps({"history": history, "datos": datos_nuevos}, ensure_ascii=False)
        db.commit()

        return {"response": mensaje_bot}

    except Exception as e:
        logger.error(f"[AraBot-JSON] Error: {e}", exc_info=True)
        return {"response": "Ocurrio un error. Por favor intenta de nuevo."}
    finally:
        db.close()
