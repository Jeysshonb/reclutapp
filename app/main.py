"""
reclutapp — sistema de reclutamiento Grupo Jerónimo Martins.
Ejecutar localmente:
    uvicorn app.main:app --reload
"""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import get_settings
from app.database import Base, engine
from app.routers import auth, candidatos, archivos, export, admin

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="reclutapp",
    version=settings.APP_VERSION,
    docs_url="/api/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/api/redoc" if settings.APP_ENV != "production" else None,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api")
app.include_router(candidatos.router, prefix="/api")
app.include_router(archivos.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

# ── Archivos estáticos ─────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=os.path.join(_BASE_DIR, "app", "static")), name="static")

_img_dir = os.path.join(_BASE_DIR, "IMG")
if os.path.isdir(_img_dir):
    app.mount("/img", StaticFiles(directory=_img_dir), name="img")

_uploads_dir = os.path.join(_BASE_DIR, "data", "uploads")
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")


_STATIC = os.path.join(_BASE_DIR, "app", "static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(_STATIC, "index.html"))


@app.get("/captura", include_in_schema=False)
async def captura():
    return FileResponse(os.path.join(_STATIC, "captura.html"))


@app.get("/seguimiento", include_in_schema=False)
async def seguimiento_page():
    return FileResponse(os.path.join(_STATIC, "seguimiento.html"))


@app.get("/admin", include_in_schema=False)
async def admin_panel():
    return FileResponse(os.path.join(_STATIC, "admin.html"))


@app.get("/health", tags=["sistema"])
async def health():
    return {"status": "ok", "version": settings.APP_VERSION, "app": "reclutapp"}


# ── Startup ────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    import bcrypt as _bcrypt
    from app.database import SessionLocal
    from app.models.candidato import Usuario

    db_dir = os.path.dirname(settings.DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    Base.metadata.create_all(bind=engine)

    def _hash(clave: str) -> str:
        return _bcrypt.hashpw(clave.encode(), _bcrypt.gensalt()).decode()

    db = SessionLocal()
    try:
        usuarios_seed = [
            ("jeysshon.bustos@jeronimo-martins.com",          "Jeysshon Bustos",                    "Jey@*1019",                           "administrador"),
            ("sthefanny.robles@jeronimo-martins.com",          "Sthefanny Robles",                   "sthefanny.robles@*",                  "especialista"),
            ("reclutador3@jeronimo-martins.com",               "Alejandra Suarez",                   "reclutador3@*",                       "especialista"),
            ("reclutador5@jeronimo-martins.com",               "Maria Alejandra Ortiz Toquica",      "reclutador5@*",                       "especialista"),
            ("reclutador6@jeronimo-martins.com",               "Leidy Fernanda Olivera Diaz",        "reclutador6@*",                       "especialista"),
            ("reclutador7@jeronimo-martins.com",               "Franchesca Isabel Bueno Amador",     "reclutador7@*",                       "especialista"),
            ("reclutador8@jeronimo-martins.com",               "Caren Daniela Velasco Torres",       "reclutador8@*",                       "especialista"),
            ("reclutador12@jeronimo-martins.com",              "Angela Orozco",                      "reclutador12@*",                      "especialista"),
            ("reclutador14@jeronimo-martins.com",              "Andrea Lucia Estupiñan Garcia",      "reclutador14@*",                      "especialista"),
            ("reclutador18@jeronimo-martins.com",              "Wendy Lizeth Herrera Buitrago",      "reclutador18@*",                      "especialista"),
            ("reclutador19@jeronimo-martins.com",              "Yudy Alexandra Sanchez Herrera",     "reclutador19@*",                      "especialista"),
            ("reclutador20@jeronimo-martins.com",              "Valentina Garavito",                 "reclutador20@*",                      "especialista"),
            ("helen.prieto@jeronimo-martins.com",              "Helen Prieto",                       "helen.prieto@*",                      "especialista"),
            ("astrid.triana@jeronimo-martins.com",             "Valentina Triana",                   "astrid.triana@*",                     "especialista"),
            ("laura.daniela.sanchez@jeronimo-martins.com",     "Laura Daniela Sanchez",              "laura.daniela.sanchez@*",             "especialista"),
            ("aura.carranza@jeronimo-martins.com",             "Carolina Carranza Herrera",          "aura.carranza@*",                     "especialista"),
            ("nathali.castellanos@jeronimo-martins.com",       "Nathali Castellanos Hernandez",      "nathali.castellanos@*",               "especialista"),
            ("karen.yerarditd.hernandez@jeronimo-martins.com", "Karen Yerarditd Hernandez Bonilla",  "karen.yerarditd.hernandez@*",         "especialista"),
            ("laura.serrano@jeronimo-martins.com",             "Laura Nataly Serrano Perdomo",       "laura.serrano@*",                     "especialista"),
            ("jerly.gomez@jeronimo-martins.com",               "Jerly Carolina Gomez Piraquive",     "jerly.gomez@*",                       "especialista"),
        ]
        for email, nombre, clave, rol in usuarios_seed:
            if not db.query(Usuario).filter_by(email=email).first():
                db.add(Usuario(
                    email=email,
                    nombre_display=nombre,
                    password_hash=_hash(clave),
                    rol=rol,
                    activo=True,
                ))
        db.commit()
    finally:
        db.close()

    import threading
    threading.Thread(target=_seed_catalogos, daemon=True).start()

    from app.services import blob_service
    if settings.AZURE_STORAGE_CONNECTION_STRING:
        blob_service.init_blob(
            settings.AZURE_STORAGE_CONNECTION_STRING,
            settings.AZURE_BLOB_CONTAINER,
        )
    else:
        blob_service.init_local(os.path.join(_BASE_DIR, "data", "uploads"))


def _seed_catalogos():
    """Siembra catálogos base de reclutamiento."""
    from app.database import SessionLocal
    from app.models.candidato import (
        CatNegocio, CatCargo, CatFuenteHV, CatResultado,
        CatDepartamento, CatMotivoRetiro, CatReclutador, CatProveedor,
    )

    db = SessionLocal()
    try:
        def _seed(modelo, valores):
            for v in valores:
                if not db.query(modelo).filter_by(nombre=v).first():
                    db.add(modelo(nombre=v))

        _seed(CatNegocio, ["Tiendas Ara", "BDC", "CEDI"])

        _seed(CatCargo, [
            "Operador de Tienda en Formación", "Operador de Tienda",
            "Operador de Tienda y Montacarga", "Operador y Montacarga CEDI",
            "Operador Part Time", "Supervisor Junior de Tienda",
            "Supervisor de Tienda", "Jefe de Tienda", "Jefe de Tienda BDC",
            "Aprendiz SENA",
        ])

        _seed(CatFuenteHV, [
            "Computrabajo", "Magneto", "Magneto Frío", "Indeed",
            "SENA", "Referido", "Redes Sociales", "Feria Laboral",
            "Voz a Voz", "Base de Datos Interna",
        ])

        _seed(CatResultado, [
            "Apto", "No Apto", "Aplazado", "No Asiste", "Desiste",
            "Apto como Operador", "No Apto EMO", "No Apto ES",
        ])

        _seed(CatDepartamento, [
            "Amazonas", "Antioquia", "Arauca", "Atlántico", "Bolívar",
            "Boyacá", "Caldas", "Caquetá", "Casanare", "Cauca",
            "Cesar", "Chocó", "Córdoba", "Cundinamarca", "Guainía",
            "Guaviare", "Huila", "La Guajira", "Magdalena", "Meta",
            "Nariño", "Norte de Santander", "Putumayo", "Quindío",
            "Risaralda", "San Andrés y Providencia", "Santander",
            "Sucre", "Tolima", "Valle del Cauca", "Vaupés", "Vichada",
            "Bogotá D.C.",
        ])

        _seed(CatMotivoRetiro, [
            "Terminación de contrato", "Retiro Voluntario",
            "Terminación sin Justa Causa", "Terminación con Justa Causa",
            "Contrato Suspendido", "Fin de obra o labor", "Mutuo acuerdo",
        ])

        _seed(CatReclutador, [
            "Alejandra Suarez", "Andrea Estupiñan", "Angela Orozco",
            "Daniela Gomez", "Leidy Olivera", "Maria Alejandra Ortiz Toquica",
            "Sthefanny Robles", "Yudy Sanchez",
        ])

        _seed(CatProveedor, ["Soandes", "RG", "Otra"])

        db.commit()
        logger.info("Catálogos reclutapp sembrados correctamente.")
    except Exception as e:
        logger.error(f"Error sembrando catálogos: {e}")
        db.rollback()
    finally:
        db.close()
