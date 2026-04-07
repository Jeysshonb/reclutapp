"""
Webhook de Twilio WhatsApp — AraBot, agente IA de reclutamiento Tiendas Ara.
- Recoge datos personales, laborales y de experiencia del candidato.
- Guarda datos parciales si el candidato abandona > 30 minutos.
- Retoma la conversación si el candidato vuelve a escribir.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from openai import AsyncAzureOpenAI

from fastapi import APIRouter, Form, Response
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.candidato import Candidato, WaSession
from app.config import get_settings
from app.ciudades_ara import buscar_ciudad

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["whatsapp"])

TIMEOUT_MINUTOS = 5

DOMINIOS_EMAIL = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com",
                  "live.com", "hotmail.es", "yahoo.es", "outlook.es")

MENSAJE_CONSENTIMIENTO = (
    "¡Hola! 👋 Soy *AraBot*, el asistente virtual de *Tiendas Ara* — Grupo Jerónimo Martins Colombia.\n\n"
    "Voy a ayudarte a registrar tu perfil para nuestras vacantes 🛒\n\n"
    "Al responder *SÍ*, autorizas el tratamiento de tus datos personales para el proceso de selección, "
    "conforme a la Ley 1581 de 2012 (Habeas Data).\n\n"
    "¿Aceptas? Responde *SÍ* para continuar 😊"
)

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
Eres *AraBot*, el asistente virtual de reclutamiento de *Tiendas Ara* (Grupo Jerónimo Martins, Colombia).
Tienes 50 años de experiencia en selección de personal operativo en retail colombiano.
Eres cálido, directo, profesional y conoces perfectamente los perfiles que busca Ara.

TU MISIÓN: Entrevistar al candidato por WhatsApp y recopilar sus datos de forma natural y amigable.
Habla como un reclutador experto de verdad — no como un formulario. Puedes combinar varias preguntas
en un mensaje cuando sea natural. Si el candidato da información sin que se la pidas, captúrala.
Si el candidato envía su hoja de vida como documento, extrae todos los datos que puedas de ella.

ORDEN DE RECOLECCIÓN — sigue este orden:
1. cedula: PRIMERO SIEMPRE — pídela si no la tienes
2. nombre_completo
3. Los demás en el orden que fluya mejor

DATOS PERSONALES:
- cedula: número de cédula (solo dígitos) — PRIMER dato a recopilar
- nombre_completo: nombre completo
- fecha_nacimiento: DD/MM/AAAA
- genero: Masculino / Femenino / Otro
- correo: correo electrónico (solo acepta dominios comunes: gmail, hotmail, outlook, yahoo, icloud, live)
- ciudad_aplica: ciudad donde aplica (el departamento se determina automáticamente)

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
- Para correo: si el dominio no es gmail/hotmail/outlook/yahoo/icloud/live, pregunta si es correcto.
- Cuando tengas los 16 datos, despídete indicando que un reclutador lo contactará pronto.

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
- "completo": true SOLO cuando los 16 campos tengan valor (no null).
- "mensaje" es exactamente lo que se envía por WhatsApp.
"""


# ── Cliente Azure OpenAI (singleton — reutiliza conexión HTTP) ─────────────────

_openai_client: AsyncAzureOpenAI | None = None

def _get_client() -> AsyncAzureOpenAI | None:
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    s = get_settings()
    if not s.AZURE_OPENAI_ENDPOINT or not s.AZURE_OPENAI_KEY:
        return None
    _openai_client = AsyncAzureOpenAI(
        azure_endpoint=s.AZURE_OPENAI_ENDPOINT,
        api_key=s.AZURE_OPENAI_KEY,
        api_version=s.AZURE_OPENAI_API_VERSION,
    )
    return _openai_client


# ── Helpers ───────────────────────────────────────────────────────────────────

def _twiml(text: str) -> Response:
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Response(
        content=f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{safe}</Message></Response>",
        media_type="application/xml",
    )


def _get_or_create_session(db: Session, phone: str, initial_step: str = "activo") -> WaSession:
    s = db.query(WaSession).filter(WaSession.phone == phone).first()
    if not s:
        s = WaSession(phone=phone, step=initial_step, data=json.dumps({"history": [], "datos": {}, "meta": {}}))
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


async def _llamar_ia(history: list, user_msg: str, datos: dict, nombre: str | None = None) -> dict:
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
        resp = await client.chat.completions.create(
            model=s.AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0.3,
            max_tokens=380,
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


def _enriquecer_con_ciudad(datos: dict) -> dict:
    """Auto-rellena departamento, zona y cod_reg a partir de ciudad_aplica."""
    ciudad = datos.get("ciudad_aplica")
    if not ciudad:
        return datos
    info = buscar_ciudad(ciudad)
    if info:
        datos["departamento"] = info.get("departamento")
        datos["zona"] = info.get("zona")
        datos["cod_reg"] = info.get("cod_reg")
    return datos


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
            zona=datos.get("zona"),
            region=datos.get("cod_reg"),
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
                await asyncio.to_thread(_guardar_candidato, datos, phone, True)
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

        # ── Si ya terminó → bloquear hasta que reclutador libere ─────────────
        if session.step == "done":
            if msg.strip() == "0":
                history, datos = [], {}
                session.step = "activo"
                session.data = json.dumps({"history": [], "datos": {}})
                db.commit()
            else:
                return _twiml(
                    "Hola 👋 Ya tienes un proceso de selección activo con Tiendas Ara. "
                    "Un reclutador te contactará pronto.\n\n"
                    "Si deseas iniciar un nuevo proceso, escribe *0*."
                )

        # ── Llamar a la IA ────────────────────────────────────────────────────
        result = await _llamar_ia(history, msg, datos)
        mensaje_bot = result["mensaje"]
        datos_nuevos = _enriquecer_con_ciudad(result["datos"])
        completo = result.get("completo", False)

        # Actualizar historial (máx 40 turnos)
        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": mensaje_bot})
        if len(history) > 20:
            history = history[-20:]

        if completo:
            session.step = "done"
            await asyncio.to_thread(_guardar_candidato, datos_nuevos, phone, False)
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

from fastapi import Body as FBody, Depends
from pydantic import BaseModel
from app.database import get_db
from app.routers.auth import get_current_user

class WaMensaje(BaseModel):
    phone: str
    message: str
    nombre: str | None = None
    imagen_base64: str | None = None
    imagen_mimetype: str | None = "image/jpeg"
    audio_base64: str | None = None
    audio_mimetype: str | None = None
    documento_base64: str | None = None
    documento_mimetype: str | None = None
    documento_nombre: str | None = None

async def _transcribir_audio(audio_b64: str, mimetype: str) -> str | None:
    """Transcribe un audio de WhatsApp usando Azure OpenAI Whisper."""
    s = get_settings()
    if not s.AZURE_WHISPER_DEPLOYMENT:
        logger.error("[AraBot] AZURE_WHISPER_DEPLOYMENT no configurado")
        return None
    client = _get_client()
    if not client:
        return None
    import base64, io as _io
    audio_bytes = base64.b64decode(audio_b64)
    # WhatsApp ptt llega como ogg/opus — renombrar a .mp4 mejora compatibilidad con Whisper
    ext = "mp4"
    if "wav" in mimetype: ext = "wav"
    elif "mpeg" in mimetype or "mp3" in mimetype: ext = "mp3"
    elif "webm" in mimetype: ext = "webm"
    audio_file = _io.BytesIO(audio_bytes)
    audio_file.name = f"audio.{ext}"
    try:
        transcript = await client.audio.transcriptions.create(
            model=s.AZURE_WHISPER_DEPLOYMENT,
            file=(audio_file.name, audio_bytes, mimetype.split(";")[0].strip()),
        )
        return transcript.text
    except Exception as e:
        logger.error(f"[AraBot] Error transcribiendo audio (mime={mimetype}): {e}")
        return f"__ERROR_AUDIO__: {str(e)[:200]}"


async def _extraer_texto_documento(doc_b64: str, mimetype: str, nombre: str) -> str | None:
    """Extrae texto de PDF, Word o Excel enviado como hoja de vida."""
    import base64, io as _io
    try:
        data = base64.b64decode(doc_b64)
        nombre_lower = nombre.lower()
        if "pdf" in mimetype or nombre_lower.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(_io.BytesIO(data))
            texto = "\n".join(p.extract_text() or "" for p in reader.pages)
            return texto[:3000].strip() or None
        elif "word" in mimetype or "docx" in mimetype or nombre_lower.endswith((".docx", ".doc")):
            from docx import Document
            doc = Document(_io.BytesIO(data))
            texto = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return texto[:3000].strip() or None
        elif "sheet" in mimetype or "excel" in mimetype or nombre_lower.endswith((".xlsx", ".xls")):
            import openpyxl
            wb = openpyxl.load_workbook(_io.BytesIO(data))
            lineas = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    fila = " | ".join(str(c) for c in row if c is not None)
                    if fila.strip():
                        lineas.append(fila)
            return "\n".join(lineas)[:3000].strip() or None
    except Exception as e:
        logger.error(f"[AraBot] Error extrayendo documento: {e}")
        return f"__ERROR_DOC__: {str(e)[:150]}"
    return None


def _generar_resumen(datos: dict) -> str:
    campos = [
        ("nombre_completo", "Nombre"),
        ("cedula", "Cédula"),
        ("fecha_nacimiento", "Nacimiento"),
        ("genero", "Género"),
        ("correo", "Correo"),
        ("ciudad_aplica", "Ciudad"),
        ("departamento", "Departamento"),
        ("cargo", "Cargo al que aplica"),
        ("fuente", "Cómo se enteró"),
        ("nivel_academico", "Educación"),
        ("situacion_laboral", "Situación laboral"),
        ("aspiracion_salarial", "Aspiración salarial"),
        ("tiene_hijos", "Tiene hijos"),
        ("disponibilidad_desplazamiento", "Disponible para desplazarse"),
        ("exp1_empresa", "Empresa anterior"),
        ("exp1_cargo", "Cargo anterior"),
        ("exp1_tiempo", "Tiempo de experiencia"),
    ]
    lineas = ["📋 *Resumen de tu registro:*\n"]
    for key, label in campos:
        val = datos.get(key)
        if val:
            if key == "aspiracion_salarial":
                try:
                    val = f"${int(float(str(val))):,}".replace(",", ".")
                except Exception:
                    pass
            lineas.append(f"• {label}: {val}")
    lineas.append("\nUn reclutador de Tiendas Ara te contactará pronto. ¡Mucha suerte! 🍀")
    return "\n".join(lineas)


def _resumen_candidato_existente(c: Candidato) -> str:
    estado_map = {
        "En Proceso": "tu proceso está activo y en revisión",
        "Seleccionado": "fuiste seleccionado — un reclutador te contactará",
        "Descartado": "tu proceso fue finalizado",
    }
    estado_txt = estado_map.get(c.status or "", "tienes un registro activo")
    return (
        f"Hola {c.nombre or 'candidato'} 👋\n\n"
        f"Ya tienes un registro en Tiendas Ara — {estado_txt}.\n\n"
        f"📋 *Tu información registrada:*\n"
        f"• Cédula: {c.cedula or 'N/A'}\n"
        f"• Cargo: {c.cargo or 'N/A'}\n"
        f"• Ciudad: {c.ciudad_aplica or 'N/A'}\n"
        f"• Estado: {c.status or 'N/A'}\n\n"
        "Si necesitas actualizar tu información, escribe tu número de cédula o contacta a un reclutador."
    )


async def _extraer_cedula_imagen(imagen_b64: str, mimetype: str) -> dict:
    """Usa GPT-4o vision para extraer datos de una foto de cédula colombiana."""
    client = _get_client()
    if not client:
        return {}
    s = get_settings()
    try:
        resp = await client.chat.completions.create(
            model=s.AZURE_OPENAI_DEPLOYMENT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Esta es una foto de una cédula de ciudadanía colombiana. "
                            "Extrae los datos visibles y devuelve SOLO este JSON sin markdown:\n"
                            '{"nombre_completo":null,"cedula":null,"fecha_nacimiento":null,"genero":null}\n'
                            "- nombre_completo: nombre completo como aparece en la cédula\n"
                            "- cedula: solo dígitos del número de documento\n"
                            "- fecha_nacimiento: formato DD/MM/AAAA\n"
                            "- genero: Masculino o Femenino según la cédula\n"
                            "Si un dato no es legible, deja null."
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mimetype};base64,{imagen_b64}", "detail": "high"}
                    }
                ]
            }],
            temperature=0,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content or ""
        logger.info(f"[AraBot] Respuesta GPT vision: {raw[:200]}")
        # Limpiar markdown si viene con ```json ... ```
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[-2] if "```" in clean[3:] else clean
            clean = clean.lstrip("`").lstrip("json").strip()
        return json.loads(clean)
    except Exception as e:
        logger.error(f"[AraBot] Error leyendo cédula: {e}")
        return {"__error__": str(e)[:100]}


def _cargar_datos_candidato(c: Candidato) -> dict:
    return {k: v for k, v in {
        "nombre_completo": c.nombre,
        "cedula": c.cedula,
        "fecha_nacimiento": c.fecha_nacimiento,
        "genero": c.genero,
        "correo": c.correo,
        "ciudad_aplica": c.ciudad_aplica,
        "departamento": c.departamento,
        "cargo": c.cargo,
        "fuente": c.fuente,
        "nivel_academico": c.nivel_academico,
        "situacion_laboral": c.situacion_laboral,
        "aspiracion_salarial": str(int(c.aspiracion_salarial)) if c.aspiracion_salarial else None,
        "tiene_hijos": "Sí" if c.tiene_hijos else ("No" if c.tiene_hijos is not None else None),
        "disponibilidad_desplazamiento": "Sí" if c.disponibilidad_desplazamiento else ("No" if c.disponibilidad_desplazamiento is not None else None),
        "exp1_empresa": c.exp1_empresa,
        "exp1_cargo": c.exp1_cargo,
        "exp1_tiempo": c.exp1_funciones,
    }.items() if v is not None}


@router.post("/whatsapp/json")
async def whatsapp_json(payload: WaMensaje):
    """Endpoint para el bot Node.js (whatsapp-web.js). Recibe JSON, devuelve JSON."""
    phone = payload.phone.strip()
    msg = payload.message.strip()

    db = SessionLocal()
    try:
        session = _get_or_create_session(db, phone, initial_step="consent")
        state = json.loads(session.data or "{}")
        history = state.get("history", [])
        datos = state.get("datos", {})
        meta = state.get("meta", {})

        # ── Consentimiento inicial ─────────────────────────────────────────────
        if session.step == "consent":
            msg_lower = msg.lower().strip()
            afirmativo = any(w in msg_lower for w in ["si", "sí", "yes", "ok", "dale", "claro", "acepto", "listo", "okay", "sure", "1"])
            if afirmativo:
                session.step = "activo"
                session.data = json.dumps({"history": [], "datos": {}, "meta": {}})
                db.commit()
                return {"response": (
                    "¡Perfecto! Gracias por aceptar 😊\n\n"
                    "Para comenzar, necesito tu *número de cédula*. Por favor escríbelo."
                )}
            else:
                return {"response": MENSAJE_CONSENTIMIENTO}

        # ── Si ya terminó → bloquear ──────────────────────────────────────────
        if session.step == "done":
            cedula_msg = msg.strip().replace(" ", "")
            cand_tel = db.query(Candidato).filter(
                Candidato.telefono_contacto == phone,
                Candidato.deleted_at.is_(None)
            ).order_by(Candidato.created_at.desc()).first()

            if cedula_msg.isdigit() and 7 <= len(cedula_msg) <= 12:
                cand_ced = db.query(Candidato).filter(
                    Candidato.cedula == cedula_msg,
                    Candidato.deleted_at.is_(None)
                ).order_by(Candidato.created_at.desc()).first()
                if cand_ced:
                    datos = _cargar_datos_candidato(cand_ced)
                    history = []
                    meta = {"cedula_verificada": True}
                    session.step = "activo"
                    session.data = json.dumps({"history": [], "datos": datos, "meta": meta})
                    db.commit()
                else:
                    return {"response": "No encontre registro con esa cedula. Escribe 0 para iniciar un proceso nuevo."}

            elif payload.nombre and cand_tel:
                wa_words = set(payload.nombre.lower().split())
                stored_words = set((cand_tel.nombre or "").lower().split())
                if not wa_words & stored_words:
                    history, datos, meta = [], {}, {}
                    session.step = "consent"
                    session.data = json.dumps({"history": [], "datos": {}, "meta": {}})
                    db.commit()
                    return {"response": MENSAJE_CONSENTIMIENTO}
                else:
                    return {"response": _resumen_candidato_existente(cand_tel)}

            elif msg.strip() == "0":
                history, datos, meta = [], {}, {}
                session.step = "consent"
                session.data = json.dumps({"history": [], "datos": {}, "meta": {}})
                db.commit()
                return {"response": MENSAJE_CONSENTIMIENTO}

            else:
                return {"response": _resumen_candidato_existente(cand_tel) if cand_tel else (
                    "Ya tienes un proceso activo con Tiendas Ara. Un reclutador te contactara pronto.\n\n"
                    "Escribe tu numero de cedula para retomar, o 0 para nuevo proceso."
                )}

        # ── Procesar medios ────────────────────────────────────────────────────
        if msg in ("[audio]", "[documento]", "[foto_cedula]") or not msg:
            if payload.audio_base64:
                s_cfg = get_settings()
                if not s_cfg.AZURE_WHISPER_DEPLOYMENT:
                    return {"response": "Por el momento no puedo procesar audios 🎤 Por favor *escribe* tu respuesta en texto."}
                texto = await _transcribir_audio(payload.audio_base64, payload.audio_mimetype or "audio/ogg")
                if texto and not texto.startswith("__ERROR_AUDIO__"):
                    msg = texto
                    logger.info(f"[AraBot] Audio transcrito {phone}: {texto[:60]}")
                elif texto and texto.startswith("__ERROR_AUDIO__"):
                    return {"response": "Por el momento no puedo procesar audios 🎤 Por favor *escribe* tu respuesta en texto."}
                else:
                    return {"response": "Por el momento no puedo procesar audios 🎤 Por favor *escribe* tu respuesta en texto."}

            elif payload.documento_base64:
                texto = await _extraer_texto_documento(
                    payload.documento_base64,
                    payload.documento_mimetype or "",
                    payload.documento_nombre or "documento"
                )
                if texto and texto.startswith("__ERROR_DOC__"):
                    logger.error(f"[AraBot] Doc error {phone}: {texto}")
                    return {"response": "No pude leer el documento 😕 Si es un PDF escaneado (imagen), no puedo extraer texto. Por favor envíalo en Word o PDF con texto digital."}
                elif texto:
                    msg = f"[Hoja de vida enviada. Información extraída:\n{texto[:2000]}]"
                    logger.info(f"[AraBot] Documento procesado {phone}: {len(texto)} chars")
                else:
                    return {"response": "No pude leer el documento 😕 Si es un PDF escaneado (imagen), no puedo extraer texto. Por favor envíalo en Word o PDF con texto digital."}

            elif payload.imagen_base64:
                extraidos = await _extraer_cedula_imagen(payload.imagen_base64, payload.imagen_mimetype or "image/jpeg")
                if "__error__" in extraidos:
                    return {"response": f"Error al leer imagen: {extraidos['__error__']}"}
                campos_utiles = {k: v for k, v in extraidos.items() if v is not None}
                if campos_utiles:
                    datos.update(campos_utiles)
                    logger.info(f"[AraBot] Cédula leída {phone}: {', '.join(campos_utiles)}")
                    msg = f"[imagen de cédula — datos extraídos: {json.dumps(campos_utiles, ensure_ascii=False)}]"
                else:
                    return {"response": "No pude leer los datos de la imagen 😕 Intenta con mejor iluminación o envía la foto más derecha."}

            elif not msg:
                return {"response": "No recibí tu mensaje. Por favor intenta de nuevo."}

        # ── Timeout ────────────────────────────────────────────────────────────
        ahora = datetime.now(timezone.utc)
        ultima = session.updated_at
        if ultima and ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        tiempo_inactivo = (ahora - ultima).total_seconds() / 60 if ultima else 0

        if session.step == "activo" and tiempo_inactivo > TIMEOUT_MINUTOS:
            tiene_datos = any(v is not None for v in datos.values())
            if tiene_datos:
                await asyncio.to_thread(_guardar_candidato, datos, phone, True)
                session.step = "done"
                session.data = json.dumps({"history": [], "datos": datos, "meta": meta})
                db.commit()
                cedula_guardada = datos.get("cedula")
                if cedula_guardada:
                    return {"response": (
                        f"⏰ Tu conversación quedó guardada por inactividad.\n\n"
                        f"Puedes retomar tu registro cuando quieras escribiendo tu número de cédula *{cedula_guardada}*."
                    )}
                else:
                    return {"response": (
                        "⏰ Tu conversación quedó guardada por inactividad.\n\n"
                        "Puedes retomar tu registro cuando quieras escribiendo tu número de cédula."
                    )}
            else:
                history, datos, meta = [], {}, {}
                session.step = "consent"
                session.data = json.dumps({"history": [], "datos": {}, "meta": {}})
                db.commit()
                return {"response": MENSAJE_CONSENTIMIENTO}

        # ── Llamar IA ──────────────────────────────────────────────────────────
        result = await _llamar_ia(history, msg, datos, nombre=payload.nombre)
        mensaje_bot = result["mensaje"]
        datos_nuevos = _enriquecer_con_ciudad(result["datos"])
        completo = result.get("completo", False)

        # ── Verificar cédula en DB (primera vez que se captura) ────────────────
        cedula_nueva = datos_nuevos.get("cedula")
        if cedula_nueva and not meta.get("cedula_verificada"):
            meta["cedula_verificada"] = True
            cand_existente = db.query(Candidato).filter(
                Candidato.cedula == str(cedula_nueva),
                Candidato.deleted_at.is_(None)
            ).order_by(Candidato.created_at.desc()).first()

            if cand_existente:
                if "Incompleto" in (cand_existente.status or ""):
                    # Cargar datos del registro incompleto y continuar
                    datos_cargados = _cargar_datos_candidato(cand_existente)
                    datos_nuevos = {**datos_cargados, **{k: v for k, v in datos_nuevos.items() if v is not None}}
                    result2 = await _llamar_ia(
                        [],
                        f"[retomando proceso incompleto — datos ya registrados: {json.dumps(datos_nuevos, ensure_ascii=False)}]",
                        datos_nuevos,
                        nombre=payload.nombre
                    )
                    mensaje_bot = result2["mensaje"]
                    datos_nuevos = _enriquecer_con_ciudad(result2["datos"])
                    completo = result2.get("completo", False)
                    history = []
                else:
                    # Registro completo/en proceso → mostrar resumen y bloquear
                    session.step = "done"
                    session.data = json.dumps({"history": [], "datos": datos_nuevos, "meta": meta}, ensure_ascii=False)
                    db.commit()
                    return {"response": _resumen_candidato_existente(cand_existente)}

        # ── Actualizar historial ───────────────────────────────────────────────
        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": mensaje_bot})
        if len(history) > 20:
            history = history[-20:]

        if completo:
            session.step = "done"
            await asyncio.to_thread(_guardar_candidato, datos_nuevos, phone, False)
            resumen = _generar_resumen(datos_nuevos)
            mensaje_final = f"{mensaje_bot}\n\n{resumen}"
        else:
            session.step = "activo"
            mensaje_final = mensaje_bot

        session.data = json.dumps({"history": history, "datos": datos_nuevos, "meta": meta}, ensure_ascii=False)
        db.commit()

        return {"response": mensaje_final}

    except Exception as e:
        logger.error(f"[AraBot-JSON] Error: {e}", exc_info=True)
        return {"response": "Ocurrio un error. Por favor intenta de nuevo."}
    finally:
        db.close()


@router.delete("/whatsapp/sesion/{phone}")
def liberar_sesion_bot(
    phone: str,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    """Libera la sesión del bot para un teléfono — el candidato puede iniciar nuevo proceso."""
    session = db.query(WaSession).filter(WaSession.phone == phone).first()
    if session:
        db.delete(session)
        db.commit()
    return {"ok": True, "phone": phone}
