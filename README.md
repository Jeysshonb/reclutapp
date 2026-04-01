# Reclutamiento ISIS

Sistema interno de seguimiento de procesos de selección para Grupo Jerónimo Martins.

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Base de datos | Azure Database for MySQL Flexible Server 8.0 |
| Hosting | Azure App Service (Linux B2) |
| Autenticación | Microsoft Entra ID (OAuth2 / OIDC) |
| Secretos | Azure Key Vault |
| CI/CD | GitHub Actions + OIDC |
| IaC | Bicep |

## Estructura del repositorio

```
reclutamiento_isis/
├── app/
│   ├── main.py                 # Punto de entrada FastAPI
│   ├── config.py               # Configuración / variables de entorno
│   ├── database.py             # SQLAlchemy engine + sesión
│   ├── models/proceso.py       # Modelos ORM
│   ├── schemas/proceso.py      # Schemas Pydantic (validación)
│   ├── routers/
│   │   ├── auth.py             # Autenticación Entra ID
│   │   ├── procesos.py         # CRUD procesos de selección
│   │   └── export.py           # Exportación Excel/CSV
│   ├── services/
│   │   ├── auth.py             # Validación JWT Entra ID
│   │   └── export.py           # Generación Excel/CSV
│   └── static/
│       ├── index.html          # Login
│       ├── captura.html        # Formulario de captura
│       └── seguimiento.html    # Pantalla de seguimiento
├── sql/
│   └── init.sql                # DDL completo + catálogos iniciales
├── infra/
│   ├── main.bicep              # Infraestructura Azure
│   └── parameters/prod.bicepparam
├── .github/workflows/
│   ├── deploy.yml              # CI/CD aplicación
│   └── infra.yml               # CI/CD infraestructura
├── startup.sh                  # Script de inicio App Service
├── requirements.txt
├── .env.example
└── .gitignore
```

## Desarrollo local

```bash
# 1. Clonar y entrar al repo
git clone https://github.com/Jeysshonb/reclutamiento_isis
cd reclutamiento_isis

# 2. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus valores locales

# 5. Inicializar base de datos local (MySQL debe estar corriendo)
mysql -u root -p < sql/init.sql

# 6. Iniciar servidor
uvicorn app.main:app --reload

# La aplicación queda disponible en http://localhost:8000
# Docs Swagger en http://localhost:8000/api/docs
```

## Despliegue en Azure

### Pre-requisitos

1. Resource Group creado en Azure
2. App Registration en Entra ID con:
   - Redirect URI: `https://<tu-app>.azurewebsites.net`
   - API Permission: `User.Read`
3. Service Principal con permiso de Contributor sobre el Resource Group
4. Workload Identity Federation configurado para GitHub Actions OIDC

### Secrets de GitHub (Settings → Secrets and variables → Actions)

| Secret | Descripción |
|---|---|
| `AZURE_CLIENT_ID` | Client ID del Service Principal (OIDC) |
| `AZURE_TENANT_ID` | Tenant ID de Azure |
| `AZURE_SUBSCRIPTION_ID` | Subscription ID |
| `AZURE_RESOURCE_GROUP` | Nombre del Resource Group |
| `AZURE_WEBAPP_NAME` | Nombre del App Service (ej. `app-isis-rec-prod`) |
| `MYSQL_ADMIN_PASSWORD` | Password del admin de MySQL |
| `ENTRA_CLIENT_ID` | Client ID de la App Registration |
| `ENTRA_TENANT_ID` | Tenant ID de Entra ID |
| `ENTRA_CLIENT_SECRET` | Client Secret de la App Registration |

### Pasos de despliegue

```bash
# 1. Desplegar infraestructura (primera vez o cambios en infra/)
# Esto se hace automáticamente con push a main que modifique infra/
# O manualmente: Actions → "Infra · Bicep Deploy" → Run workflow

# 2. Desplegar aplicación
# Automático con push a main
# O manualmente: Actions → "App · Build & Deploy" → Run workflow

# 3. Inicializar base de datos (una sola vez)
# Conectarse al MySQL vía Azure Portal → Connect → Cloud Shell
# mysql -h <host> -u mysqladmin -p reclutamiento_isis < sql/init.sql

# 4. Configurar el primer usuario administrador
# INSERT INTO usuarios (entra_oid, email, nombre_display, rol)
# VALUES ('<tu-oid-de-entra>', 'tu@email.com', 'Tu Nombre', 'administrador');
```

## Conexión App Service → MySQL Flexible Server

Azure App Service se conecta al MySQL Flexible Server mediante:

1. **Firewall rule** `AllowAzureServices` (IP 0.0.0.0 → 0.0.0.0): permite tráfico interno de Azure
2. **SSL obligatorio**: `MYSQL_SSL=true` con certificado CA de Azure
3. **Cadena de conexión**: `mysql+pymysql://<user>:<pass>@<host>:3306/<db>?ssl_ca=/etc/ssl/certs/ca-certificates.crt`
4. **Password desde Key Vault**: `@Microsoft.KeyVault(SecretUri=...)` en App Settings

Para mayor seguridad en producción: integrar ambos servicios en una **VNet** con Private Endpoint.

## Roles y permisos

| Rol | Permisos |
|---|---|
| `administrador` | CRUD completo + eliminar + gestionar usuarios |
| `editor` | Crear y editar procesos |
| `consulta` | Solo lectura y exportación |

## API Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/auth/me` | Información del usuario actual |
| GET | `/api/procesos` | Listar procesos (filtros + paginación) |
| POST | `/api/procesos` | Crear proceso |
| GET | `/api/procesos/{id}` | Obtener proceso |
| PUT | `/api/procesos/{id}` | Actualizar proceso |
| DELETE | `/api/procesos/{id}` | Eliminar proceso (soft delete) |
| GET | `/api/procesos/{id}/historial` | Historial de cambios |
| GET | `/api/export/excel` | Exportar a Excel |
| GET | `/api/export/csv` | Exportar a CSV |
| GET | `/api/procesos/catalogos/estatus` | Catálogo de estatus |
| GET | `/api/procesos/catalogos/tipo-proceso` | Catálogo de tipos |
| GET | `/api/procesos/catalogos/proveedor` | Catálogo de proveedores |
| GET | `/health` | Health check |
