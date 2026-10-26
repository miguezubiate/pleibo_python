# Arquitectura y decisiones técnicas para la prueba

## 1. Flujo de una petición

Cliente HTTPS -> Caddy -> Gunicorn -> Flask -> schema -> autorización -> servicio -> SQLAlchemy -> MySQL. El cliente Ghibli usa HTTPS hacia un proveedor con URL configurable. Redis mantiene revocaciones, cuotas y caché compartida entre los workers.

Flask se crea mediante application factory. Las extensiones se inicializan sin acoplarse a una instancia global. Las vistas gestionan el contrato HTTP; los servicios controlan escrituras y transacciones. SQLAlchemy encapsula persistencia con consultas parametrizadas. No se añade un repositorio que solo duplique cada método del ORM: se puede extraer cuando existan consultas complejas o varios proveedores de persistencia.

## 2. Autenticación frente a autorización

Autenticación: login verifica el hash scrypt y emite un JWT de 15 minutos. Autorización: cada petición valida firma, emisor, audiencia, expiración, jti revocado, usuario existente, token_version y rol actual en MySQL. Un JWT por sí solo no autoriza una operación.

| Rol | CRUD usuarios | Perfil propio | Ghibli |
|---|---|---|---|
| admin | Sí | Sí | Los cinco recursos |
| films | No | Sí | films |
| people | No | Sí | people |
| locations | No | Sí | locations |
| species | No | Sí | species |
| vehicles | No | Sí | vehicles |

Los roles se asignan explícitamente por un admin. El primer admin se crea desde la CLI en el host autorizado. No existe endpoint de bootstrap público ni contraseña predeterminada. El rol no se confía a una entrada arbitraria del JWT; se consulta su estado actual.

Se aplica autorización antes de cargar cuerpos y de acceder a Ghibli o a su caché. Así, el usuario films no puede acceder a una respuesta people almacenada por un admin. Login usa un hash de verificación de relleno cuando el correo no existe y responde con un mensaje genérico para no revelar cuentas directamente.

## 3. Integridad y concurrencia

Email se normaliza a minúsculas y tiene restricción UNIQUE; role tiene CHECK en MySQL. La validación de aplicación permite errores útiles y la base protege ante carreras. Una transacción abarca toda la modificación o borrado múltiple. Ante una excepción se ejecuta rollback antes de responder.

La fila única security_lock se bloquea con SELECT FOR UPDATE para cada escritura de usuario. Tras tomar el lock se vuelve a comprobar el actor y se verifica que queda al menos un admin antes del commit. MySQL usa READ COMMITTED para que una petición que esperó un lock observe el cambio confirmado por la anterior. La prueba concurrente del pipeline elimina simultáneamente dos admins y exige conservar uno.

Decisión: serializar las escrituras de usuarios es simple y protege esta invariante, pero limita su throughput. Es apropiado para un CRUD administrativo de carga moderada. Para cientos de escrituras por segundo conviene separar la protección de admins y diseñar locks más específicos, midiendo primero. SQLite no reproduce locks InnoDB: por eso existe la matriz MySQL en CI.

Borrado físico, no lógico: cumple el alcance y revoca acceso, pero no conserva el historial de usuario. En un sistema con obligaciones de retención habría que definir anonimización, auditoría persistente y borrado lógico antes de ampliar el dominio.

## 4. Fallos y observabilidad

Ghibli tiene timeout (2 s conexión, 4 s lectura por intento), máximo un reintento de GET, respuestas 502/504 y caché compartida de 60 s. No hay retry de escrituras. No se implementa circuit breaker: en cargas altas se debe añadir para contener una caída prolongada, junto con métricas de latencia y error. Las listas Ghibli utilizan limit; no se promete paginación de un proveedor que no la ofrezca.

El logging registra método, ruta sin query string, estado, duración y un request_id generado por el servidor. Los eventos de alta/cambio/baja identifican actor y destino sin contraseñas, tokens ni cuerpos. No es un sistema de auditoría inmutable. Los errores de dependencias se registran por tipo para evitar filtrar cadenas de conexión.

Liveness valida el proceso. Readiness consulta MySQL y Redis; Ghibli queda fuera para no retirar toda la API por una falla externa. Los balanceadores deben usar readiness, y el monitoreo de Ghibli debe ser independiente. Un healthcheck de Docker detecta enfermedad pero por sí solo no reinicia un contenedor que sigue vivo; un operador o supervisor debe actuar si permanece unhealthy.

## 5. Escalabilidad y distribución

Los workers Gunicorn no guardan sesiones locales. Redis compartido coordina logout, cuotas y caché. La conexión a MySQL usa pool, pre_ping y reciclado para conexiones cerradas por el servidor. La suma de conexiones posibles crece con workers e instancias: ajustar frente a max_connections y métricas, no aumentar workers a ciegas.

Despliegue incluido: una EC2 x86_64 con Caddy, API, MySQL y Redis en Docker. Es reproducible y sencillo de evaluar, pero hay un único punto de falla y breve interrupción al reemplazar la API. Un volumen Docker no sustituye un backup externo.

Evolución para alta disponibilidad: ALB con certificado ACM -> Auto Scaling con 2+ EC2 en distintas AZ -> RDS MySQL Multi-AZ y Redis compartido con autenticación/TLS. Retirar MySQL/Redis locales, cambiar DATABASE_URL/REDIS_URL, suministrar CA de RDS y exigir TLS a la base. Ajustar ProxyFix al número real de proxies de confianza y restringir los Security Groups. Las migraciones siguen siendo un único job, nunca cada réplica. Esta topología no está aprovisionada por el proyecto.

Las revocaciones son seguridad, no solo caché. Redis usa AOF y noeviction en el despliegue incluido. Si se pierde su volumen, tokens previamente revocados podrían volver a ser válidos hasta expirar; en recuperación de desastre debe rotarse JWT_SECRET_KEY antes de restablecer el servicio. La persistencia no elimina todo riesgo de pérdida. Separar almacenamiento de sesiones y caché al crecer para que la caché no consuma memoria necesaria para revocaciones.

## 6. CI/CD y cadena de suministro

Pull requests ejecutan lint, tests SQLite/MySQL/Redis, cobertura y auditoría de dependencias. Solo main publica en ECR. GitHub obtiene credenciales efímeras con OIDC, no claves AWS permanentes. SSM ejecuta el script en una instancia específica y el workflow comprueba el estado final remoto.

La aplicación se despliega por digest sha256, no por latest. Las versiones Python están fijadas, pero las imágenes base y acciones usan tags: para un entorno con requisitos de cadena de suministro estrictos, fijar también sus digests/SHAs revisados, añadir escaneo de imagen, SBOM y firma. ECR debe tener escaneo habilitado; el pipeline incluido bloquea vulnerabilidades Python detectadas por pip-audit, pero no implementa una puerta automática de hallazgos ECR.

Las migraciones compatibles preceden al cambio de contenedor. Si falla el arranque, se intenta restaurar la imagen anterior; no se ejecuta downgrade automático de esquema. Usar patrón expand/contract: añadir campos compatibles, desplegar consumidores y solo después retirar campos en otra versión. Si la migración falla, se detiene el despliegue; DDL MySQL puede tener efectos parciales y requiere inspección.

## 7. Alcance y ampliaciones

No incluye frontend, MFA, recuperación de contraseña, registro público, refresh tokens, circuit breaker, WAF, infraestructura Terraform, ALB ni carga de imágenes. Son ampliaciones explícitas, no funcionalidades simuladas. La configuración, código y pruebas son una base operable que debe validarse en staging con la infraestructura y carga real antes de pasar a producción.
