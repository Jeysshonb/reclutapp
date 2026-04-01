"""
Modelos ORM para reclutapp — sistema de reclutamiento Grupo Jerónimo Martins.
"""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, func
from app.database import Base


# ── Catálogos ─────────────────────────────────────────────────────────────────

class CatNegocio(Base):
    __tablename__ = "cat_negocio"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False, unique=True)
    activo = Column(Boolean, default=True)


class CatCargo(Base):
    __tablename__ = "cat_cargo"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    negocio = Column(String(100))
    activo = Column(Boolean, default=True)


class CatFuenteHV(Base):
    __tablename__ = "cat_fuente_hv"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False, unique=True)
    activo = Column(Boolean, default=True)


class CatResultado(Base):
    __tablename__ = "cat_resultado"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False, unique=True)
    activo = Column(Boolean, default=True)


class CatDepartamento(Base):
    __tablename__ = "cat_departamento"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False, unique=True)
    activo = Column(Boolean, default=True)


class CatMunicipio(Base):
    __tablename__ = "cat_municipio"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False)
    departamento = Column(String(100))
    activo = Column(Boolean, default=True)


class CatMotivoRetiro(Base):
    __tablename__ = "cat_motivo_retiro"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False, unique=True)
    activo = Column(Boolean, default=True)


class CatReclutador(Base):
    __tablename__ = "cat_reclutador"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    email = Column(String(150))
    activo = Column(Boolean, default=True)


class CatProveedor(Base):
    __tablename__ = "cat_proveedor"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    tipo = Column(String(10))  # EMO o ES
    activo = Column(Boolean, default=True)


# ── Usuario ───────────────────────────────────────────────────────────────────

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    nombre_display = Column(String(150), nullable=False)
    email = Column(String(150), nullable=False, unique=True)
    password_hash = Column(String(200), nullable=False)
    rol = Column(String(30), nullable=False, default="consulta")  # administrador | especialista | consulta
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


# ── Candidato — registro completo del proceso ────────────────────────────────

class Candidato(Base):
    __tablename__ = "candidatos"

    id = Column(Integer, primary_key=True, index=True)

    # ── Sección 1: Metadata ──────────────────────────────────────────────────
    reclutador = Column(String(150))
    zona = Column(String(50))
    region = Column(String(20))
    negocio = Column(String(100))           # Tiendas Ara / BDC / CEDI
    tipo_formulario = Column(String(100))   # ODT / SDT-JDT / Part Time / SENA
    cargo = Column(String(150))
    fuente = Column(String(100))            # Computrabajo, Magneto, SENA...
    ciudad_aplica = Column(String(100))
    observaciones_analistas = Column(Text)

    # ── Sección 2: Datos personales ──────────────────────────────────────────
    cedula = Column(String(30), index=True, nullable=False)
    tipo_documento = Column(String(50), default="Cédula de Ciudadanía")
    nombre = Column(String(200), nullable=False)
    fecha_nacimiento = Column(String(20))
    genero = Column(String(20))
    correo = Column(String(150))
    telefono_contacto = Column(String(100))  # puede tener varios separados por /
    direccion = Column(String(250))          # incluye barrio
    departamento = Column(String(100))
    municipio = Column(String(100))
    localidad = Column(String(100))          # solo Bogotá

    # ── Sección 3: Medidas ───────────────────────────────────────────────────
    talla_pantalon = Column(String(10))
    talla_camiseta = Column(String(10))
    talla_zapatos = Column(String(10))
    peso = Column(Float)
    altura = Column(Float)
    imc = Column(Float)
    resultado_imc = Column(String(50))  # Sano / Sobrepeso / Alerta...

    # ── Sección 4: Inclusión laboral ─────────────────────────────────────────
    tiene_discapacidad = Column(Boolean, default=False)
    tipo_discapacidad = Column(String(200))
    tiene_certificado_discapacidad = Column(Boolean, default=False)

    # ── Sección 5: Familia y disponibilidad ─────────────────────────────────
    tiene_hijos = Column(Boolean, default=False)
    num_hijos = Column(Integer)
    edades_hijos = Column(String(100))
    apoyo_cuidado = Column(String(200))
    familiar_en_ara = Column(Boolean, default=False)
    quien_familiar_ara = Column(String(200))
    medio_transporte = Column(String(50))   # Moto / Carro / Bicicleta / No tiene
    disponibilidad_desplazamiento = Column(Boolean, default=False)
    destino_desplazamiento = Column(String(200))
    disponibilidad_reubicacion = Column(Boolean, default=False)
    destino_reubicacion = Column(String(200))
    comentarios_disponibilidad = Column(Text)

    # ── Sección 6: Educación ─────────────────────────────────────────────────
    nivel_academico = Column(String(50))
    anio_graduacion = Column(String(10))
    titulo = Column(String(200))
    estudia_actualmente = Column(Boolean, default=False)
    modalidad_estudio = Column(String(50))
    proyectos_corto_plazo = Column(Text)

    # ── Sección 7: Situación laboral ─────────────────────────────────────────
    situacion_laboral = Column(String(50))
    tipo_contrato = Column(String(50))
    salario_actual = Column(Float)
    aspiracion_salarial = Column(Float)
    meses_desempleado = Column(Integer)
    justificacion_cambio_indefinido = Column(Text)

    # ── Sección 8: Experiencia laboral (3 registros) ─────────────────────────
    exp1_empresa = Column(String(200))
    exp1_cargo = Column(String(150))
    exp1_actividad = Column(String(200))
    exp1_ciudad = Column(String(100))
    exp1_salario = Column(Float)
    exp1_fecha_inicio = Column(String(20))
    exp1_fecha_retiro = Column(String(20))
    exp1_funciones = Column(Text)
    exp1_motivo_retiro = Column(String(150))
    exp1_argumentacion_mr = Column(Text)
    exp1_tiene_certificado = Column(Boolean, default=False)

    exp2_empresa = Column(String(200))
    exp2_cargo = Column(String(150))
    exp2_actividad = Column(String(200))
    exp2_ciudad = Column(String(100))
    exp2_salario = Column(Float)
    exp2_fecha_inicio = Column(String(20))
    exp2_fecha_retiro = Column(String(20))
    exp2_funciones = Column(Text)
    exp2_motivo_retiro = Column(String(150))
    exp2_argumentacion_mr = Column(Text)
    exp2_tiene_certificado = Column(Boolean, default=False)

    exp3_empresa = Column(String(200))
    exp3_cargo = Column(String(150))
    exp3_actividad = Column(String(200))
    exp3_ciudad = Column(String(100))
    exp3_salario = Column(Float)
    exp3_fecha_inicio = Column(String(20))
    exp3_fecha_retiro = Column(String(20))
    exp3_funciones = Column(Text)
    exp3_motivo_retiro = Column(String(150))
    exp3_argumentacion_mr = Column(Text)
    exp3_tiene_certificado = Column(Boolean, default=False)

    # ── Pipeline: Entrevista Operaciones ─────────────────────────────────────
    fecha_prog_operaciones = Column(String(20))
    hora_operaciones = Column(String(10))
    lugar_operaciones = Column(String(150))
    entrevistador_1 = Column(String(150))
    fecha_retro_operaciones = Column(String(20))
    resultado_operaciones = Column(String(50))   # Apto / No Apto / No Asiste / Aplazado
    comentarios_operaciones = Column(Text)

    # ── Pipeline: Entrevista RRHH ─────────────────────────────────────────────
    fecha_prog_rrhh = Column(String(20))
    entrevistador_2 = Column(String(150))
    fecha_retro_rrhh = Column(String(20))
    resultado_rrhh = Column(String(50))          # Apto / No Apto
    comentarios_rrhh = Column(Text)

    # ── Pipeline: EMO (Examen médico ocupacional) ─────────────────────────────
    fecha_envio_emo = Column(String(20))
    fecha_recibido_emo = Column(String(20))
    concepto_emo = Column(String(100))           # Apto / No Apto EMO
    proveedor_emo = Column(String(150))
    comentarios_emo = Column(Text)
    facturacion_emo = Column(String(100))

    # ── Pipeline: ES (Estudio de seguridad) ───────────────────────────────────
    fecha_envio_es = Column(String(20))
    fecha_recibido_es = Column(String(20))
    concepto_es = Column(String(100))            # Apto / No Apto ES
    proveedor_es = Column(String(150))
    comentarios_es = Column(Text)
    facturacion_es = Column(String(100))

    # ── Contratación ──────────────────────────────────────────────────────────
    fecha_contratacion = Column(String(20))
    status = Column(String(80), default="En Proceso")
    # Contratado / No Apto / No Apto EMO / No Apto ES / No Asiste / Desiste / En Proceso
    tipo_status = Column(String(80))
    comentarios_status = Column(Text)
    correo_agradecimiento = Column(Boolean, default=False)
    comunicacion_candidatos = Column(Text)
    gestion_hello = Column(Boolean, default=False)

    # ── Flags especiales ──────────────────────────────────────────────────────
    lista_negra = Column(Boolean, default=False)
    motivo_lista_negra = Column(Text)

    # ── Auditoría ─────────────────────────────────────────────────────────────
    creado_por = Column(String(150))
    actualizado_por = Column(String(150))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime, nullable=True)


# ── Archivos adjuntos ─────────────────────────────────────────────────────────

class ArchivoCandidato(Base):
    __tablename__ = "archivos_candidato"
    id = Column(Integer, primary_key=True)
    candidato_id = Column(Integer, ForeignKey("candidatos.id"), nullable=False)
    nombre_original = Column(String(250))
    blob_name = Column(String(250))
    blob_url = Column(Text)
    tipo = Column(String(100))
    tamanio_bytes = Column(Integer)
    etapa = Column(String(50), default="general")   # operaciones|rrhh|emo|es|contratacion|general
    subido_por_id = Column(Integer, ForeignKey("usuarios.id"))
    created_at = Column(DateTime, server_default=func.now())


# ── Sesión WhatsApp bot ───────────────────────────────────────────────────────

class WaSession(Base):
    __tablename__ = "wa_sessions"
    id = Column(Integer, primary_key=True)
    phone = Column(String(30), nullable=False, unique=True, index=True)
    step = Column(String(50), nullable=False, default="start")
    data = Column(Text, default="{}")   # JSON con datos recolectados
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ── Auditoría de cambios ───────────────────────────────────────────────────────

class Auditoria(Base):
    __tablename__ = "auditoria"
    id = Column(Integer, primary_key=True)
    candidato_id = Column(Integer, ForeignKey("candidatos.id"))
    usuario = Column(String(150))
    accion = Column(String(50))     # CREATE / UPDATE / DELETE
    detalle = Column(Text)
    timestamp = Column(DateTime, server_default=func.now())
