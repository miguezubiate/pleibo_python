# Users Auth & Studio Ghibli API (Prueba PLEIBO)

Proyecto Python 3.12 + Flask, MySQL 8.4, SQLAlchemy, JWT, Redis, Swagger y Docker.
Incluye CI/CD para AWS EC2 mediante GitHub Actions, ECR y Systems Manager.

## Inicio rápido (Windows, macOS o Linux)

Instala Docker Engine con Compose v2 o Docker Desktop y Python 3.12. En Windows utiliza contenedores Linux; los comandos siguientes pueden ejecutarse en PowerShell (usa `python` o `py -3.12`).

```bash
python scripts/init_env.py
docker compose up --build -d
docker compose ps -a
docker compose logs migrate api
docker compose exec api flask --app wsgi:app create-admin
```

El script genera contraseñas aleatorias; no existe usuario ni contraseña por defecto. La CLI solicita nombre, correo y contraseña (mínimo 12 caracteres). `.env` nunca se sube a Git. Si ya existe, el generador se detiene para evitar reemplazar secretos.

MySQL y Redis arrancan primero; un contenedor separado ejecuta las migraciones y termina con código 0. Después inicia Gunicorn. El estado `Exited (0)` de `migrate` es normal.

- Swagger UI: http://localhost:8000/docs
- OpenAPI JSON: http://localhost:8000/openapi.json
- Readiness: http://localhost:8000/health/ready
- Liveness: http://localhost:8000/health/live

En Swagger, ejecuta `POST /api/v1/auth/login` con el admin creado. Copia `access_token`, pulsa **Authorize** y pega solamente el token (sin escribir `Bearer`). Crea usuarios y prueba los roles.

## Ejemplo de uso

Cuerpo de login:

```json
{"email":"admin@example.com","password":"TU_PASSWORD_DE_12_O_MAS_CARACTERES"}
```

Para crear un usuario, utiliza `POST /api/v1/users` y el encabezado `Authorization: Bearer <token>`:

```json
{
  "name": "Miguel",
  "email": "miguel@example.com",
  "password": "CAMBIA_ESTA_PASSWORD_2026",
  "role": "films"
}
```

Inicia sesión con Miguel y llama a `GET /api/v1/ghibli/films`. `GET /api/v1/ghibli/people` devuelve 403. El admin puede consultar las cinco colecciones. No se permite registro público ni asignación de roles por usuarios normales.

## Contrato REST

| Método y ruta | Permiso | Resultado |
|---|---|---|
| POST /api/v1/auth/login | Público, limitado | JWT de 15 minutos |
| POST /api/v1/auth/logout | Autenticado | Revoca el token actual, 204 |
| GET /api/v1/users/me | Autenticado | Perfil propio |
| POST /api/v1/users | admin | Creación, 201 |
| GET /api/v1/users?page=1&per_page=20 | admin | Lista paginada, máximo 100 |
| GET /api/v1/users/{id} | admin | Un usuario |
| PATCH /api/v1/users/{id} | admin | Actualización parcial |
| DELETE /api/v1/users/{id} | admin | Borrado físico, 204 |
| POST /api/v1/users/bulk-delete | admin | Borrado atómico de IDs |
| GET /api/v1/ghibli/{resource}?limit=50 | admin o rol igual al recurso | Colección |
| GET /api/v1/ghibli/{resource}/{uuid} | admin o rol igual al recurso | Detalle |

Borrado múltiple: `{"ids":[2,3,4]}`; máximo 100, IDs repetidos se deduplican. Si uno no existe o se eliminaría al último admin, toda la operación se revierte. Se usa POST para la operación masiva para evitar problemas de interoperabilidad con cuerpos en DELETE. La actualización usa PATCH, no reemplazo completo PUT.

Errores: 400 JSON mal formado; 401 credenciales/token; 403 rol; 404 inexistente; 409 correo duplicado o último admin; 413 cuerpo grande; 422 validación; 429 cuota; 502 proveedor inválido; 503 MySQL/Redis; 504 timeout Ghibli. Las contraseñas y hashes nunca forman parte de las respuestas.

## Ejecutar pruebas y revisión

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell, en lugar del comando anterior:
# .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
ruff check .
pytest
pip-audit -r requirements.txt
```

Sin variables adicionales, las pruebas utilizan SQLite temporal, fakeredis y HTTP simulado. No acceden al Ghibli externo. GitHub Actions ejecuta además las pruebas con MySQL 8.4 real y Redis real; comprueba bloqueo concurrente del último administrador y límites de login. No uses una base con datos reales para las pruebas: limpian la tabla users.

Para ejecutarlas contra servicios de prueba propios:

```bash
export TEST_DATABASE_URL='mysql+pymysql://tester:password@127.0.0.1:3306/ghibli_test'
export TEST_REDIS_URL='redis://127.0.0.1:6379/15'
pytest
```

El pipeline exige mínimo 80% de cobertura y bloquea la publicación si fallan pruebas, lint o auditoría de dependencias. Dependencias Python directas y transitivas quedan fijadas a las versiones instaladas. Dependabot propone actualizaciones; deben volver a probarse.

## Estructura

- `app/__init__.py`: factory, configuración, errores, logging, CLI.
- `app/routes.py`: HTTP, documentación y autorización.
- `app/schemas.py`: validación y serialización sin campos secretos.
- `app/services.py`: transacciones, invariantes y operaciones de usuarios.
- `app/security.py`: JWT, revocación y consulta de permisos actuales.
- `app/models.py`: entidades y restricciones de base de datos.
- `app/ghibli.py`: cliente externo, caché y errores del proveedor.
- `migrations/`: historial Alembic; no se usa create_all en producción.
- `tests/`: pruebas de contrato, seguridad, errores e integración.
- `deploy/`: Compose productivo, HTTPS, despliegue, backup y políticas IAM.
- `.github/workflows/ci-cd.yml`: pruebas, construcción y despliegue.
- `docs/`: decisiones, operación AWS, fuentes y validación realizada.

## Seguridad y operación

JWT firmado HS256, emisor y audiencia verificados, expiración de 15 minutos y contraseña con scrypt. Un cambio de contraseña o rol incrementa token_version e invalida sesiones anteriores. La baja invalida el acceso porque se consulta el usuario en cada petición. Logout guarda el jti en Redis hasta que vence. Si Redis falla, el acceso falla cerrado. Se requiere nuevo login al vencer; no hay refresh token.

Se limita login por IP (5/minuto) y peticiones generales por IP (120/minuto). Es un control inicial, no reemplaza protección perimetral ni MFA. CORS no se abre globalmente. No se usan cookies de autenticación. HTTPS es obligatorio fuera de localhost. `TRUST_PROXY=true` solo cuando Gunicorn está detrás del proxy definido y su puerto no es público.

Las lecturas de Ghibli tienen caché compartida de 60 segundos, timeout de conexión/lectura y un reintento acotado de GET. El recurso es una lista permitida y el ID debe ser UUID; no se recibe una URL arbitraria del cliente. Ghibli es una API comunitaria externa sin SLA contratado.

El Compose local publica 8000 solamente en localhost; MySQL/Redis no publican puertos. Para AWS usa exclusivamente el Compose productivo y los pasos de `docs/AWS_EC2.md`. No ejecutes `flask run` en producción.

## Actualizaciones y datos

```bash
docker compose down
# Volver a iniciar sin borrar datos:
docker compose up --build -d
```

Los volúmenes conservan MySQL/Redis. `docker compose down -v` BORRA los datos: no usar en producción. Cambiar MYSQL_PASSWORD en `.env` no cambia una contraseña que ya existe en MySQL: debe rotarse con SQL y actualizar la configuración de manera coordinada.

El proyecto entrega una base de despliegue en una EC2, no alta disponibilidad. Lee `docs/ARQUITECTURA.md` para escalar con ALB, múltiples instancias, RDS y Redis compartido. Los recursos de AWS, DNS, roles IAM y variables de GitHub deben crearse en tu cuenta. No se ha ejecutado un despliegue en AWS como parte de este entregable.
