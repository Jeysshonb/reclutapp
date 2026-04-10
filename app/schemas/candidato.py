"""
Schemas Pydantic para reclutapp.
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    nombre_display: str
    rol: str


# ── Usuarios ──────────────────────────────────────────────────────────────────

class UsuarioCreate(BaseModel):
    email: str
    nombre_display: str
    password: str
    rol: str = "consulta"


class UsuarioUpdate(BaseModel):
    email: Optional[str] = None
    nombre_display: Optional[str] = None
    rol: Optional[str] = None
    activo: Optional[bool] = None
    password: Optional[str] = None


class UsuarioOut(BaseModel):
    id: int
    email: str
    nombre_display: str
    rol: str
    activo: bool

    class Config:
        from_attributes = True


# ── Catálogos ─────────────────────────────────────────────────────────────────

class CatalogoItem(BaseModel):
    id: int
    nombre: str
    activo: bool

    class Config:
        from_attributes = True


class CatalogoCreate(BaseModel):
    nombre: str


# ── Candidato ─────────────────────────────────────────────────────────────────

class CandidatoBase(BaseModel):
    # Metadata
    reclutador: Optional[str] = None
    zona: Optional[str] = None
    region: Optional[str] = None
    negocio: Optional[str] = None
    tipo_formulario: Optional[str] = None
    cargo: Optional[str] = None
    fuente: Optional[str] = None
    ciudad_aplica: Optional[str] = None
    observaciones_analistas: Optional[str] = None

    # Datos personales
    cedula: str
    tipo_documento: Optional[str] = "Cédula de Ciudadanía"
    nombre: str
    fecha_nacimiento: Optional[str] = None
    genero: Optional[str] = None
    correo: Optional[str] = None
    telefono_contacto: Optional[str] = None
    direccion: Optional[str] = None
    departamento: Optional[str] = None
    municipio: Optional[str] = None
    localidad: Optional[str] = None

    # Medidas
    talla_pantalon: Optional[str] = None
    talla_camiseta: Optional[str] = None
    talla_zapatos: Optional[str] = None
    peso: Optional[float] = None
    altura: Optional[float] = None

    # Inclusión
    tiene_discapacidad: Optional[bool] = False
    tipo_discapacidad: Optional[str] = None
    tiene_certificado_discapacidad: Optional[bool] = False

    # Familia y disponibilidad
    tiene_hijos: Optional[bool] = False
    num_hijos: Optional[int] = None
    edades_hijos: Optional[str] = None
    apoyo_cuidado: Optional[str] = None
    familiar_en_ara: Optional[bool] = False
    quien_familiar_ara: Optional[str] = None
    medio_transporte: Optional[str] = None
    disponibilidad_desplazamiento: Optional[bool] = False
    destino_desplazamiento: Optional[str] = None
    disponibilidad_reubicacion: Optional[bool] = False
    destino_reubicacion: Optional[str] = None
    comentarios_disponibilidad: Optional[str] = None

    # Educación
    nivel_academico: Optional[str] = None
    anio_graduacion: Optional[str] = None
    titulo: Optional[str] = None
    estudia_actualmente: Optional[bool] = False
    modalidad_estudio: Optional[str] = None
    proyectos_corto_plazo: Optional[str] = None

    # Situación laboral
    situacion_laboral: Optional[str] = None
    tipo_contrato: Optional[str] = None
    salario_actual: Optional[float] = None
    aspiracion_salarial: Optional[float] = None
    meses_desempleado: Optional[int] = None
    justificacion_cambio_indefinido: Optional[str] = None

    # Experiencia 1
    exp1_empresa: Optional[str] = None
    exp1_cargo: Optional[str] = None
    exp1_actividad: Optional[str] = None
    exp1_ciudad: Optional[str] = None
    exp1_salario: Optional[float] = None
    exp1_fecha_inicio: Optional[str] = None
    exp1_fecha_retiro: Optional[str] = None
    exp1_funciones: Optional[str] = None
    exp1_motivo_retiro: Optional[str] = None
    exp1_argumentacion_mr: Optional[str] = None
    exp1_tiene_certificado: Optional[bool] = False

    # Experiencia 2
    exp2_empresa: Optional[str] = None
    exp2_cargo: Optional[str] = None
    exp2_actividad: Optional[str] = None
    exp2_ciudad: Optional[str] = None
    exp2_salario: Optional[float] = None
    exp2_fecha_inicio: Optional[str] = None
    exp2_fecha_retiro: Optional[str] = None
    exp2_funciones: Optional[str] = None
    exp2_motivo_retiro: Optional[str] = None
    exp2_argumentacion_mr: Optional[str] = None
    exp2_tiene_certificado: Optional[bool] = False

    # Experiencia 3
    exp3_empresa: Optional[str] = None
    exp3_cargo: Optional[str] = None
    exp3_actividad: Optional[str] = None
    exp3_ciudad: Optional[str] = None
    exp3_salario: Optional[float] = None
    exp3_fecha_inicio: Optional[str] = None
    exp3_fecha_retiro: Optional[str] = None
    exp3_funciones: Optional[str] = None
    exp3_motivo_retiro: Optional[str] = None
    exp3_argumentacion_mr: Optional[str] = None
    exp3_tiene_certificado: Optional[bool] = False

    # Pipeline - Operaciones
    fecha_prog_operaciones: Optional[str] = None
    hora_operaciones: Optional[str] = None
    lugar_operaciones: Optional[str] = None
    entrevistador_1: Optional[str] = None
    fecha_retro_operaciones: Optional[str] = None
    resultado_operaciones: Optional[str] = None
    comentarios_operaciones: Optional[str] = None

    # Pipeline - RRHH
    fecha_prog_rrhh: Optional[str] = None
    entrevistador_2: Optional[str] = None
    fecha_retro_rrhh: Optional[str] = None
    resultado_rrhh: Optional[str] = None
    comentarios_rrhh: Optional[str] = None

    # Pipeline - EMO
    fecha_envio_emo: Optional[str] = None
    fecha_recibido_emo: Optional[str] = None
    concepto_emo: Optional[str] = None
    proveedor_emo: Optional[str] = None
    comentarios_emo: Optional[str] = None
    facturacion_emo: Optional[str] = None

    # Pipeline - ES
    fecha_envio_es: Optional[str] = None
    fecha_recibido_es: Optional[str] = None
    concepto_es: Optional[str] = None
    proveedor_es: Optional[str] = None
    comentarios_es: Optional[str] = None
    facturacion_es: Optional[str] = None

    # Contratación
    fecha_contratacion: Optional[str] = None
    status: Optional[str] = "En Proceso"
    tipo_status: Optional[str] = None
    comentarios_status: Optional[str] = None
    correo_agradecimiento: Optional[bool] = False
    comunicacion_candidatos: Optional[str] = None
    gestion_hello: Optional[bool] = False

    # Flags
    lista_negra: Optional[bool] = False
    motivo_lista_negra: Optional[str] = None


class CandidatoCreate(CandidatoBase):
    pass


class CandidatoUpdate(CandidatoBase):
    cedula: Optional[str] = None
    nombre: Optional[str] = None


class CandidatoOut(CandidatoBase):
    id: int
    imc: Optional[float] = None
    resultado_imc: Optional[str] = None
    creado_por: Optional[str] = None
    actualizado_por: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CandidatoResumen(BaseModel):
    """Versión resumida para la tabla del dashboard."""
    id: int
    cedula: str
    nombre: str
    cargo: Optional[str] = None
    negocio: Optional[str] = None
    reclutador: Optional[str] = None
    region: Optional[str] = None
    genero: Optional[str] = None
    ciudad_aplica: Optional[str] = None
    fuente: Optional[str] = None
    nivel_academico: Optional[str] = None
    situacion_laboral: Optional[str] = None
    aspiracion_salarial: Optional[float] = None
    telefono_contacto: Optional[str] = None
    fecha_prog_operaciones: Optional[str] = None
    resultado_operaciones: Optional[str] = None
    resultado_rrhh: Optional[str] = None
    concepto_emo: Optional[str] = None
    concepto_es: Optional[str] = None
    status: Optional[str] = None
    tipo_status: Optional[str] = None
    lista_negra: Optional[bool] = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HistorialCedula(BaseModel):
    """Historial de procesos anteriores de un candidato por cédula."""
    id: int
    nombre: str
    cargo: Optional[str] = None
    negocio: Optional[str] = None
    fecha_prog_operaciones: Optional[str] = None
    resultado_operaciones: Optional[str] = None
    resultado_rrhh: Optional[str] = None
    status: Optional[str] = None
    lista_negra: Optional[bool] = False
    motivo_lista_negra: Optional[str] = None
    comentarios_status: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
