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
from app.models.candidato import Candidato, WaSession, WaArchivo
from app.config import get_settings
from app.ciudades_ara import buscar_ciudad

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["whatsapp"])

TIMEOUT_MINUTOS = 30

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
Si el candidato envía su hoja de vida, imagen o documento: extrae TODOS los datos que puedas y responde con un resumen EXPLÍCITO así: "Encontré la siguiente información: *Nombre:* X, *Cédula:* Y, *Ciudad:* Z... ¿Todo correcto o hay algo que corregir?" Luego pregunta solo por los datos que falten.

ORDEN DE RECOLECCIÓN — sigue este orden:
1. cedula: PRIMERO SIEMPRE — ESCRIBE EXACTAMENTE ESTO (sin cambiar nada): "¿Cuál es tu número de cédula? Puedes escribirlo o enviarme una foto de la *parte frontal* de tu cédula 📸"
2. nombre_completo: cuando tengas la cédula (por foto o texto), confirma el nombre así: "Vi que tu nombre es *X* según [tu WhatsApp / tu cédula], ¿es correcto?" — si el nombre viene de la foto de cédula, úsalo directamente como nombre_completo confirmado
3. fecha_nacimiento: ESCRIBE EXACTAMENTE ESTO (sin cambiar nada): "¿Cuál es tu fecha de nacimiento? Puedes escribirla (DD/MM/AAAA) o enviarme una foto de la *parte trasera* de tu cédula 📸"
4. genero: pregunta SIEMPRE justo después de fecha_nacimiento: "¿Cuál es tu género? *Masculino*, *Femenino* u *Otro*"
5. Los demás en el orden que fluya mejor

VALIDACIÓN DE CÉDULA POR FOTO:
- Si el candidato envía una foto y se extrae cédula y/o nombre, confirma SIEMPRE: "Leí tu cédula *XXXXXXX* y tu nombre *YYYY* — ¿está correcto?"
- Solo guarda los datos si el candidato confirma (dice sí, correcto, etc.)
- Si el candidato corrige algo, actualiza el dato con lo que diga

EDAD Y CUMPLEAÑOS:
- Cuando registres fecha_nacimiento, calcula la edad usando la fecha actual que se te indica en el contexto.
- Menciona la edad naturalmente: "¡Genial! Tienes *X años* 😊"
- Si HOY es exactamente el día y mes de su cumpleaños (mismo DD/MM que la fecha actual): felicítalo PRIMERO con entusiasmo antes de continuar: "¡Feliz cumpleaños! 🎂🎉 ¡Qué bueno que estás buscando nuevas oportunidades justamente en tu día!"

DATOS PERSONALES:
- cedula: número de cédula (solo dígitos) — PRIMER dato a recopilar
- nombre_completo: nombre completo
- fecha_nacimiento: DD/MM/AAAA
- genero: Masculino / Femenino / Otro
- telefono: número de celular colombiano (10 dígitos, ej: 3001234567) — pregunta: "¿Cuál es tu número de celular para que podamos contactarte?"
- correo: correo electrónico (solo acepta dominios comunes: gmail, hotmail, outlook, yahoo, icloud, live)
- ciudad_aplica: ciudad donde aplica (el departamento se determina automáticamente).
  IMPORTANTE — si el candidato dice "Bogotá" o "Bogotá D.C.", pregunta SIEMPRE su localidad:
  "¿En qué localidad de Bogotá vives o aplicas? (ej: Kennedy, Suba, Usaquén, Engativá...)"
  Guarda en ciudad_aplica la LOCALIDAD específica (ej: "Kennedy"), NO "Bogotá".
  Localidades válidas: Barrios Unidos, Chapinero, Engativá, Fontibón, Suba, Teusaquillo, Usaquén,
  Santa Fe, Puente Aranda, Tunjuelito, Usme, Ciudad Bolívar, Rafael Uribe Uribe, San Cristóbal,
  Kennedy, Bosa, Los Mártires, Antonio Nariño.

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
- Usa máximo 1-2 emojis por mensaje (excepto en el saludo de cumpleaños que puedes usar hasta 3).
- Si algo no queda claro, pide amablemente que repita.
- Si el candidato pregunta algo sobre Ara o el proceso, respóndele brevemente antes de continuar.
- Para experiencia, si dice que no tiene, acepta "Sin experiencia" en los 3 campos de exp.
- NUNCA inventes datos que el candidato no haya dado.
- Para correo: si el dominio no es gmail/hotmail/outlook/yahoo/icloud/live, pregunta si es correcto.
- Cuando tengas los 17 datos, despídete indicando que un reclutador lo contactará pronto.

FORMATO DE RESPUESTA — SIEMPRE responde con este JSON exacto (sin markdown, sin texto extra):
{
  "mensaje": "texto que le envías al candidato",
  "datos": {
    "nombre_completo": null,
    "cedula": null,
    "fecha_nacimiento": null,
    "genero": null,
    "telefono": null,
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
- "completo": true SOLO cuando los 17 campos tengan valor (no null).
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
    # Fecha actual Colombia (UTC-5) para cálculo de edad y cumpleaños
    ahora_col = datetime.now(timezone(timedelta(hours=-5)))
    fecha_hoy = ahora_col.strftime("%d/%m/%Y")
    dia_hoy   = ahora_col.day
    mes_hoy   = ahora_col.month

    system = SYSTEM_PROMPT + f"\n\nFECHA ACTUAL (Colombia): {fecha_hoy} — usa esta fecha para calcular edades y detectar cumpleaños."
    if nombre:
        system += f"\nEl candidato se llama '{nombre}' según su perfil de WhatsApp. Salúdalo por su nombre en el primer mensaje."
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
            max_tokens=900,
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
        # Forzar completo si los 16 campos tienen valor
        campos_requeridos = ["nombre_completo","cedula","fecha_nacimiento","genero","telefono","correo",
                             "ciudad_aplica","cargo","fuente","nivel_academico","situacion_laboral",
                             "aspiracion_salarial","tiene_hijos","disponibilidad_desplazamiento",
                             "exp1_empresa","exp1_cargo","exp1_tiempo"]
        if all(merged.get(c) for c in campos_requeridos):
            result["completo"] = True
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
        tel_wa = phone.replace("whatsapp:", "")
        tel = datos.get("telefono") or tel_wa

        sal_raw = str(datos.get("aspiracion_salarial") or "0").lower()
        # "salario mínimo" / "minimo" → valor SMMLV Colombia 2025
        if any(w in sal_raw for w in ("minim", "mínimo", "minimo", "smlv", "smmlv")):
            salario = 1750905.0
        else:
            try:
                # Formato colombiano: "1.350.000" → quitar puntos de miles → float
                sal_limpio = sal_raw.replace(".", "").replace(",", "").replace("$", "").replace(" ", "")
                sal_limpio = "".join(c for c in sal_limpio if c.isdigit())
                salario = float(sal_limpio) if sal_limpio else None
            except Exception:
                salario = None

        tiene_hijos_raw = datos.get("tiene_hijos", "")
        tiene_hijos = str(tiene_hijos_raw).lower() in ("sí", "si", "s", "true", "1")

        disp_raw = datos.get("disponibilidad_desplazamiento", "")
        disponibilidad = str(disp_raw).lower() in ("sí", "si", "s", "true", "1")

        status = "Incompleto - Bot WA" if parcial else "En Proceso"
        obs = f"[{'Registro parcial' if parcial else 'Registro completo'} por AraBot vía WhatsApp]\nNúmero WA: {tel_wa}"

        # Tiempo de experiencia va en funciones si no hay campo directo
        exp_funciones = datos.get("exp1_tiempo")

        cedula_limpia = "".join(c for c in str(datos.get("cedula") or "") if c.isdigit())

        # municipio: para Bogotá es "Bogotá D.C.", para otras ciudades es ciudad_aplica
        ciudad = datos.get("ciudad_aplica")
        departamento = datos.get("departamento")
        if departamento == "Bogotá D.C.":
            municipio = "Bogotá D.C."
        else:
            municipio = ciudad

        campos = dict(
            nombre=datos.get("nombre_completo", ""),
            fecha_nacimiento=datos.get("fecha_nacimiento"),
            genero=datos.get("genero"),
            correo=datos.get("correo"),
            ciudad_aplica=ciudad,
            departamento=departamento,
            municipio=municipio,
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
        # Actualizar si ya existe (y no está borrado), crear si no
        c = db.query(Candidato).filter(
            Candidato.cedula == cedula_limpia,
            Candidato.deleted_at.is_(None)
        ).first() if cedula_limpia else None
        if c:
            for k, v in campos.items():
                if v is not None:
                    # No degradar status si ya está en un estado más avanzado que Incompleto
                    if k == "status" and parcial and c.status and "Incompleto" not in c.status:
                        continue
                    setattr(c, k, v)
        else:
            c = Candidato(cedula=cedula_limpia, **campos)
            db.add(c)
        db.commit()
        logger.info(f"[AraBot] Candidato {'parcial' if parcial else 'completo'} guardado: {c.nombre} / {tel}")
    except Exception as e:
        logger.error(f"[AraBot] ERROR guardando candidato — datos: {datos} — error: {e}", exc_info=True)
        db.rollback()
        raise  # propagar para que asyncio.to_thread lo surfacee
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
    """Extrae texto crudo de PDF, Word o Excel."""
    import base64, io as _io
    try:
        data = base64.b64decode(doc_b64)
        nombre_lower = nombre.lower()
        if "pdf" in mimetype or nombre_lower.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(_io.BytesIO(data))
            texto = "\n".join(p.extract_text() or "" for p in reader.pages)
            return texto[:4000].strip() or None
        elif "word" in mimetype or "docx" in mimetype or nombre_lower.endswith((".docx", ".doc")):
            from docx import Document
            doc = Document(_io.BytesIO(data))
            texto = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return texto[:4000].strip() or None
        elif "sheet" in mimetype or "excel" in mimetype or nombre_lower.endswith((".xlsx", ".xls")):
            import openpyxl
            wb = openpyxl.load_workbook(_io.BytesIO(data))
            lineas = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    fila = " | ".join(str(c) for c in row if c is not None)
                    if fila.strip():
                        lineas.append(fila)
            return "\n".join(lineas)[:4000].strip() or None
    except Exception as e:
        logger.error(f"[AraBot] Error extrayendo documento: {e}")
        return f"__ERROR_DOC__: {str(e)[:150]}"
    return None


async def _resumir_documento_con_gpt(texto_crudo: str) -> str:
    """Usa GPT-4o para extraer y resumir datos de reclutamiento del texto de un documento."""
    client = _get_client()
    if not client:
        return texto_crudo
    s = get_settings()
    try:
        resp = await client.chat.completions.create(
            model=s.AZURE_OPENAI_DEPLOYMENT,
            messages=[{
                "role": "user",
                "content": (
                    "Del siguiente texto de una hoja de vida u otro documento, extrae y resume "
                    "TODA la información relevante para reclutamiento. "
                    "Formato de respuesta: lista con los datos encontrados así:\n"
                    "Nombre completo: ...\nCédula: ...\nFecha nacimiento: ...\nCiudad: ...\n"
                    "Correo: ...\nTeléfono: ...\nNivel educativo: ...\nCargo al que aplica: ...\n"
                    "Experiencia laboral: (empresa, cargo, tiempo para cada una)\n"
                    "Si un dato no aparece, omítelo. Solo incluye lo que está en el texto.\n\n"
                    f"TEXTO DEL DOCUMENTO:\n{texto_crudo}"
                )
            }],
            temperature=0,
            max_tokens=600,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[AraBot] Error resumiendo documento con GPT: {e}")
        return texto_crudo


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


async def _subir_blob(data_b64: str, nombre: str, tipo: str, phone: str, cedula: str | None) -> str | None:
    """Sube un archivo a Azure Blob Storage y guarda referencia en BD (usa su propia sesión DB)."""
    import base64, uuid
    s = get_settings()
    if not s.AZURE_STORAGE_CONNECTION_STRING:
        return None
    try:
        from azure.storage.blob import BlobServiceClient

        def _upload():
            data = base64.b64decode(data_b64)
            blob_name = f"{phone}/{uuid.uuid4().hex[:8]}_{nombre}"
            client = BlobServiceClient.from_connection_string(s.AZURE_STORAGE_CONNECTION_STRING)
            container = client.get_container_client("whatsapp-docs")
            container.upload_blob(blob_name, data, overwrite=True)
            return f"https://{client.account_name}.blob.core.windows.net/whatsapp-docs/{blob_name}"

        url = await asyncio.to_thread(_upload)

        # Guardar referencia con sesión propia (el db del request puede estar cerrado)
        db2 = SessionLocal()
        try:
            archivo = WaArchivo(phone=phone, cedula=cedula, tipo=tipo, nombre=nombre, blob_url=url)
            db2.add(archivo)
            db2.commit()
        finally:
            db2.close()

        logger.info(f"[AraBot] Archivo subido: {url}")
        return url
    except Exception as e:
        logger.error(f"[AraBot] Error subiendo blob: {e}")
        return None


async def _extraer_datos_imagen(imagen_b64: str, mimetype: str) -> str:
    """Usa GPT-4o vision para extraer cualquier dato de reclutamiento visible en la imagen."""
    client = _get_client()
    if not client:
        return ""
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
                            "Analiza esta imagen. Puede ser una cédula, hoja de vida, diploma u otro documento. "
                            "Extrae TODA la información visible que sea relevante para reclutamiento: "
                            "nombre completo, número de cédula, fecha de nacimiento, género, ciudad, "
                            "correo, teléfono, nivel educativo, experiencia laboral, cargo, empresa, etc. "
                            "Devuelve un resumen en texto plano con los datos encontrados, "
                            "en formato: Campo: Valor (uno por línea). "
                            "Si no encuentras datos relevantes, di exactamente: SIN_DATOS"
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mimetype};base64,{imagen_b64}", "detail": "high"}
                    }
                ]
            }],
            temperature=0,
            max_tokens=500,
        )
        raw = resp.choices[0].message.content or ""
        logger.info(f"[AraBot] GPT vision extrajo: {raw[:200]}")
        return raw.strip()
    except Exception as e:
        logger.error(f"[AraBot] Error leyendo imagen: {e}")
        return f"__ERROR__: {str(e)[:150]}"


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
                    "¿Cuál es tu número de cédula? Puedes escribirlo o enviarme una foto de la *parte frontal* de tu cédula 📸"
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
                return {"response": "No puedo procesar audios 🎤 Por favor *escribe* tu respuesta en texto."}

            elif payload.documento_base64:
                cedula_actual = datos.get("cedula")
                nombre_doc = payload.documento_nombre or "documento"
                asyncio.create_task(_subir_blob(payload.documento_base64, nombre_doc, "pdf", phone, cedula_actual))
                texto = await _extraer_texto_documento(
                    payload.documento_base64,
                    payload.documento_mimetype or "",
                    nombre_doc
                )
                if texto and texto.startswith("__ERROR_DOC__"):
                    logger.error(f"[AraBot] Doc error {phone}: {texto}")
                    return {"response": "No pude leer el documento 😕 Si es un PDF escaneado (foto), envíalo como imagen directamente. Si es Word o PDF con texto, intenta de nuevo."}
                elif texto:
                    logger.info(f"[AraBot] Documento procesado {phone}: {len(texto)} chars")
                    msg = f"[El candidato envió su hoja de vida. Extrae todos los datos que encuentres (nombre, cédula, ciudad, correo, educación, experiencia, etc.) y úsalos para completar el formulario sin volver a pedirlos. Texto del documento:\n{texto[:3000]}]"
                else:
                    return {"response": "No pude leer el documento 😕 Si es un PDF escaneado (foto), envíalo como imagen directamente. Si es Word o PDF con texto, intenta de nuevo."}

            elif payload.imagen_base64:
                cedula_actual = datos.get("cedula")
                asyncio.create_task(_subir_blob(payload.imagen_base64, "imagen.jpg", "imagen", phone, cedula_actual))
                texto_imagen = await _extraer_datos_imagen(payload.imagen_base64, payload.imagen_mimetype or "image/jpeg")
                if texto_imagen.startswith("__ERROR__"):
                    return {"response": "No pude leer la imagen 😕 Intenta con mejor iluminación o más cerca."}
                elif texto_imagen == "SIN_DATOS" or not texto_imagen:
                    return {"response": "No encontré datos relevantes en la imagen 😕 Asegúrate de que el documento sea legible."}
                else:
                    logger.info(f"[AraBot] Imagen procesada {phone}: {len(texto_imagen)} chars")
                    msg = f"[El candidato envió una imagen con la siguiente información:\n{texto_imagen}]"

            elif msg == "[foto_cedula]":
                # Node.js envió [foto_cedula] pero imagen_base64 llegó vacío — error de descarga
                logger.warning(f"[AraBot] imagen_base64 vacío para {phone} — descarga fallida en bot")
                return {"response": "No pude recibir la imagen 😕 Por favor inténtalo de nuevo o escribe tu número de cédula directamente."}

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
        cedula_nueva_raw = datos_nuevos.get("cedula")
        if cedula_nueva_raw:
            # Normalizar: solo dígitos (GPT puede devolver "1.019.060.017" desde foto)
            cedula_nueva_norm = "".join(c for c in str(cedula_nueva_raw) if c.isdigit())
            if cedula_nueva_norm:
                datos_nuevos["cedula"] = cedula_nueva_norm
        cedula_nueva = datos_nuevos.get("cedula")
        if cedula_nueva and not meta.get("cedula_verificada"):
            meta["cedula_verificada"] = True
            cand_existente = db.query(Candidato).filter(
                Candidato.cedula == cedula_nueva,
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
            try:
                await asyncio.to_thread(_guardar_candidato, datos_nuevos, phone, False)
                session.step = "done"
                resumen = _generar_resumen(datos_nuevos)
                mensaje_final = f"{mensaje_bot}\n\n{resumen}"
            except Exception as save_err:
                logger.error(f"[AraBot] Fallo al guardar candidato completo: {save_err}", exc_info=True)
                session.step = "activo"
                mensaje_final = "Tuve un problema técnico al guardar tu información 😕 Por favor envía tu respuesta de nuevo en un momento."
        else:
            session.step = "activo"
            mensaje_final = mensaje_bot
            # Auto-guardar parcial en background si ya tenemos cédula + nombre
            # Así el candidato queda visible en la plataforma aunque abandone la conversación
            if datos_nuevos.get("cedula") and datos_nuevos.get("nombre_completo"):
                asyncio.create_task(asyncio.to_thread(_guardar_candidato, {**datos_nuevos}, phone, True))

        session.data = json.dumps({"history": history, "datos": datos_nuevos, "meta": meta}, ensure_ascii=False)
        db.commit()

        return {"response": mensaje_final}

    except Exception as e:
        logger.error(f"[AraBot-JSON] Error: {e}", exc_info=True)
        return {"response": "Ocurrio un error. Por favor intenta de nuevo."}
    finally:
        db.close()


class WaFixLid(BaseModel):
    lid: str
    phone: str

@router.post("/whatsapp/fix-lid")
async def fix_lid_phone(body: WaFixLid):
    """Cuando contacts.upsert resuelve un LID, actualiza sesiones/candidatos en la BD."""
    db = SessionLocal()
    try:
        # Actualizar WaSession
        session = db.query(WaSession).filter(WaSession.phone == body.lid).first()
        if session:
            session.phone = body.phone
            db.commit()
            logger.info(f"[fix-lid] WaSession: {body.lid} → {body.phone}")

        # Actualizar WaArchivo
        db.query(WaArchivo).filter(WaArchivo.phone == body.lid).update({"phone": body.phone})
        db.commit()

        # Actualizar Candidato.telefono_contacto creado por el bot
        candidato = db.query(Candidato).filter(
            Candidato.telefono_contacto == body.lid,
            Candidato.reclutador == "Bot WhatsApp"
        ).first()
        if candidato:
            candidato.telefono_contacto = body.phone
            db.commit()
            logger.info(f"[fix-lid] Candidato: {body.lid} → {body.phone}")

        return {"ok": True}
    except Exception as e:
        logger.error(f"[fix-lid] Error: {e}")
        db.rollback()
        return {"ok": False, "error": str(e)}
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
