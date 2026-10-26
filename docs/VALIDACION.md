# Validación del entregable

Fecha: 26 de octubre de 2026. Entorno disponible: Python 3.12.14 sobre Linux.

## Ejecutado y aprobado

- Pytest: 45 pruebas aprobadas y 2 omitidas con motivo explícito.
- Cobertura de aplicación: 97,15% (409 de 421 sentencias cubiertas); umbral configurado: 80%.
- Migración inicial Alembic aplicada en bases SQLite temporales de las pruebas.
- CRUD, normalización, duplicados, transacciones atómicas, último admin, expiración, logout, invalidación por rol/contraseña y matriz de los seis roles.
- Ghibli: transporte HTTP simulado; validación de caché, timeout, fallo de conexión, HTTP adverso, forma de respuesta y límites.
- Ruff: sin errores. Compilación Python: correcta. pip check: sin incompatibilidades declaradas.
- pip-audit: sin vulnerabilidades conocidas detectadas para requirements.txt en la consulta realizada. No garantiza ausencia de vulnerabilidades futuras ni audita el sistema operativo de la imagen.
- YAML/JSON: lectura sintáctica correcta. Scripts Bash: bash -n sin errores.
- Swagger / OpenAPI: endpoint generado correctamente y copia estática incluida en docs/openapi.json.

## Pendiente en infraestructura de destino

No hay Docker, MySQL ni Redis reales disponibles en el entorno de elaboración. Por ello no se ejecutaron aquí la construcción de imagen, docker compose up, el healthcheck de contenedor ni las dos pruebas específicas de Redis real y concurrencia InnoDB. La matriz GitHub Actions las ejecutará al subir el proyecto, pero el workflow aún no se ha ejecutado en tu repositorio.

No se han creado recursos AWS, iniciado EC2, publicado en ECR, configurado un dominio ni probado SSM/OIDC contra tu cuenta. Las políticas IAM requieren sustituir los marcadores por tus datos. Tampoco se ha comprobado la disponibilidad efectiva de los endpoints Ghibli mediante una llamada productiva autenticada del proyecto; las pruebas externas usan mocks para ser deterministas.

Antes de producción: ejecutar el pipeline completo, validar despliegue y TLS en staging, realizar las pruebas manuales de roles, probar backup/restauración y medir consumo de recursos/carga. No confundir cobertura de líneas con seguridad certificada o preparación operacional completa.
