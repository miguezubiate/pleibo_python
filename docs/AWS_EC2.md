# Despliegue paso a paso en AWS EC2

## 1. Preparar la cuenta y elegir el entorno
Se usa EC2 por cuestiones de expertice en el entorno de la nube.

Usa una cuenta AWS con permisos para EC2, IAM, ECR, Systems Manager y, si eliges backups externos, S3. Selecciona una región única para ECR/EC2. Necesitas un dominio o subdominio propio con registro A a la IP de la instancia para HTTPS automático de Caddy.

Este procedimiento despliega una sola EC2 con MySQL y Redis en contenedores. Para cargas críticas consulta la evolución a RDS y múltiples AZ en ARQUITECTURA.md. No es alta disponibilidad ni despliegue sin interrupción. AWS cobra por recursos usados; define presupuesto y alertas en tu cuenta antes de crearlos.

## 2. Crear ECR y roles IAM

Crea un repositorio privado ECR llamado `ghibli-users`, con tags inmutables y escaneo al subir. Desde una terminal AWS autenticada (sustituye la región):

```bash
aws ecr create-repository --repository-name ghibli-users \
  --image-tag-mutability IMMUTABLE \
  --image-scanning-configuration scanOnPush=true \
  --region us-east-1
```

Crea un rol EC2 con confianza al servicio ec2.amazonaws.com. Asocia AmazonSSMManagedInstanceCore y una política basada en deploy/ec2-ecr-policy.json, sustituyendo REGION y ACCOUNT_ID. Así la instancia puede administrarse por SSM y descargar solo el repositorio permitido. No copies claves AWS al servidor.

En IAM registra el proveedor OIDC `https://token.actions.githubusercontent.com`, audiencia `sts.amazonaws.com`. Crea otro rol para GitHub basado en deploy/github-oidc-trust.json y adjunta deploy/github-deploy-policy.json. Sustituye ACCOUNT_ID, REGION, ORG, REPO e INSTANCE_ID. El claim sub debe coincidir exactamente con tu repositorio y el environment production. Algunas configuraciones recientes de GitHub incluyen IDs inmutables en el subject: confirma el formato real en la documentación de OIDC y adapta la política; no uses un comodín para resolverlo.

La política limita ECR al repositorio y SSM a una instancia. El permiso SendCommand es sensible porque ejecuta código como root en esa EC2: restringe quién puede modificar main y aprobar production.

## 3. Crear la instancia EC2

Crea una EC2 Ubuntu Server 24.04 LTS x86_64. Como punto inicial para API+MySQL+Redis usa 2 vCPU y 4 GiB de RAM, sujeto a pruebas de carga. El pipeline construye linux/amd64; no elijas Graviton/ARM sin cambiar el build. Usa EBS gp3 cifrado, por ejemplo 30 GiB iniciales, y planifica crecimiento y snapshots.

Asocia el rol EC2 anterior. Exige IMDSv2. Si solo el host necesita credenciales, mantén el acceso a metadata limitado al host; la API no necesita AWS SDK en este alcance. Utiliza una IP estable y un registro DNS A; no crees un AAAA si no configuraste IPv6.

Security Group de entrada: TCP 80 y 443 desde los clientes esperados (Internet si el API es público). No abras 3306, 6379 ni 8000. Administración por Session Manager: no requiere exponer SSH. Permite salida HTTPS para SSM, ECR, Ghibli y certificados, y salida necesaria para instalación/actualización del sistema. Una subred privada requiere NAT o endpoints adecuados; este ejemplo asume salida a Internet y DNS resuelto.

Comprueba que la instancia aparece Online en Systems Manager. En Ubuntu verifica el agente:

```bash
sudo systemctl status snap.amazon-ssm-agent.amazon-ssm-agent.service
```

Si la AMI no incluye el agente, instálalo siguiendo la documentación AWS. No continúes al pipeline hasta que SSM funcione.

## 4. Instalar Docker y AWS CLI en EC2

Abre Session Manager. Los siguientes comandos asumen una instancia limpia Ubuntu 24.04, sin instalaciones previas de Docker. Usa el repositorio oficial:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl unzip python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
  "$(dpkg --print-architecture)" "$VERSION_CODENAME" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
```

Instala AWS CLI v2 con el instalador oficial para x86_64; verifica su firma según la guía de AWS antes de ejecutar la instalación en tu entorno:

```bash
curl -fLo /tmp/awscliv2.zip \
  https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
unzip -q /tmp/awscliv2.zip -d /tmp/awscli-install
sudo /tmp/awscli-install/aws/install
aws --version
aws sts get-caller-identity
```

La identidad debe corresponder al rol de EC2. No ejecutes aws configure con claves permanentes. Verifica Docker Compose con soporte para `--wait` y `--wait-timeout`.

## 5. Copiar archivos operativos y generar secretos

Transfiere el ZIP del proyecto mediante un canal administrativo de confianza. Puedes subirlo a un bucket S3 privado temporal de despliegue, dar al rol EC2 permiso GetObject solo sobre ese objeto y descargarlo desde Session Manager. Retira ese permiso al terminar. El archivo no debe contener .env ni claves. Descomprímelo en /tmp y entra en ghibli-users-api.

Desde ese directorio, ejecuta:

```bash
sudo install -d -m 700 /opt/ghibli
sudo install -m 600 deploy/compose.prod.yaml /opt/ghibli/compose.prod.yaml
sudo install -m 644 deploy/Caddyfile /opt/ghibli/Caddyfile
sudo install -m 700 deploy/deploy.sh /opt/ghibli/deploy.sh
sudo install -m 700 deploy/backup.sh /opt/ghibli/backup.sh
python3 scripts/init_env.py
sudo install -m 600 .env /opt/ghibli/.env
rm .env
sudo nano /opt/ghibli/.env
```

En /opt/ghibli/.env conserva los secretos aleatorios y añade/ajusta:

```dotenv
DOMAIN=api.tudominio.com
TRUST_PROXY=true
ENABLE_DOCS=false
WEB_CONCURRENCY=2
```

DATABASE_URL debe seguir apuntando al host mysql y REDIS_URL a redis dentro de Docker. No escribas valores entre comillas innecesariamente ni uses contraseñas con caracteres URL sin codificarlos; el generador usa hexadecimal para evitar ese problema. `.env` contiene secretos legibles por root y Docker: protege acceso al host y al grupo docker. Para una operación más amplia, carga secretos desde Secrets Manager durante bootstrap; no está automatizado en esta versión.

Caddyfile usa el dominio del .env a través de Compose. El dominio debe resolver correctamente y los puertos 80/443 deben ser alcanzables para emitir el certificado. Guarda copia segura de los secretos para recuperación.

## 6. Configurar GitHub y ejecutar el primer despliegue

Crea un repositorio y sube el contenido del proyecto con `.github` incluido. El ZIP no contiene un repositorio remoto preconfigurado. Configura protección de main y el environment **production**, permitiendo desplegar solo main. Si tu plan lo permite, añade revisores requeridos.

En Settings -> Environments -> production -> Environment variables configura:

| Variable | Ejemplo / contenido |
|---|---|
| AWS_REGION | us-east-1 |
| AWS_DEPLOY_ROLE_ARN | ARN del rol OIDC de GitHub |
| ECR_REPOSITORY | ghibli-users |
| EC2_INSTANCE_ID | ID real de la instancia i-... |

No son claves secretas. La contraseña MySQL y JWT_SECRET_KEY permanecen en EC2. Nunca se requieren AWS_ACCESS_KEY_ID ni AWS_SECRET_ACCESS_KEY en GitHub.

Haz push a main. El workflow prueba SQLite/MySQL, aplica migraciones en tests, valida Redis real, lint y pip-audit. Después publica la imagen en ECR y llama por SSM al script preparado. El script hace pull por digest, inicia dependencias, migra una vez, arranca API, verifica readiness y arranca Caddy. GitHub espera el estado final de SSM: enviar un comando no equivale a despliegue correcto.

Las políticas ejemplo y archivos de /opt/ghibli deben prepararse antes del primer push de despliegue. Cambios futuros en deploy.sh, compose.prod.yaml o Caddyfile requieren copiarlos al host mediante el mismo procedimiento administrativo; el pipeline actual actualiza la imagen, no reemplaza automáticamente esos archivos. Prueba dichos cambios en staging primero.

## 7. Crear el primer administrador y validar

Desde Session Manager, usa una shell root:

```bash
sudo -i
cd /opt/ghibli
export APP_IMAGE="$(cat current-image)"
docker compose -p ghibli --env-file .env -f compose.prod.yaml \
  exec api flask --app wsgi:app create-admin
docker compose -p ghibli --env-file .env -f compose.prod.yaml ps
curl --fail http://127.0.0.1:8000/health/ready
curl --fail https://api.tudominio.com/health/ready
```

Login y operaciones deben probarse con HTTPS desde un cliente externo. Comprueba: sin token -> 401; admin crea/lista -> 201/200; films consulta films -> 200 y people -> 403; logout seguido de petición -> 401; duplicado -> 409; último admin no se puede eliminar -> 409.

Swagger está deshabilitado en este ejemplo productivo. Para habilitarlo conscientemente, cambia ENABLE_DOCS=true y recrea api con el mismo digest; las operaciones siguen exigiendo JWT. El documento OpenAPI puede seguir siendo accesible sin credenciales: no contiene datos ni secretos. Para documentación estrictamente privada, bloquea /docs y /openapi.json en el proxy.

Si necesitas reiniciar manualmente después de un reboot o mantenimiento, conserva el nombre de proyecto `ghibli` y exporta APP_IMAGE desde current-image. Docker usa restart unless-stopped para los servicios persistentes. `migrate` es un job manual de despliegue, no un servicio permanente.

## 8. Rollback y migraciones

El script conserva current-image y previous-image. Si la nueva API no llega a healthy, intenta restaurar la imagen anterior. El rollback no revierte SQL. Si no existe una imagen previa (primer despliegue), se informa el fallo para corregirlo.

Rollback manual desde /opt/ghibli como root (sustituye región):

```bash
bash /opt/ghibli/deploy.sh "$(cat previous-image)" us-east-1
```

Solo aplica si el esquema actual sigue siendo compatible con la imagen anterior. Nunca ejecutes downgrade sin revisar SQL y tener backup comprobado. Para cambios incompatibles usa despliegues por etapas expand/contract y, si procede, ventana de mantenimiento. El primer esquema crea users y security_lock; las revisiones futuras se generan con `flask --app wsgi:app db migrate` en desarrollo y se revisan antes de incluirlas en Git.

## 9. Backups S3 y restauración

Crea un bucket privado de backups en tu cuenta. Activa Block Public Access, Object Ownership bucket-owner-enforced, cifrado SSE-S3 (o KMS si agregas permisos), versionado y lifecycle según tu retención. Adjunta al rol EC2 deploy/s3-backups-policy.json sustituyendo BACKUP_BUCKET. El script solo necesita PutObject sobre mysql/*; el operador de restauración debe tener GetObject por separado.

Programa diariamente backup.sh con cron de root, usando tu nombre real de bucket y con zona horaria del servidor conocida:

```cron
0 3 * * * /opt/ghibli/backup.sh mi-bucket-backups >> /var/log/ghibli-backup.log 2>&1
```

El backup usa mysqldump transaccional para InnoDB, comprime, sube a S3 y elimina el temporal. Comparte un lock con deploy.sh para evitar DDL concurrente. Una programación diaria implica potencialmente hasta un día de datos perdidos; el RTO depende de cuánto tarde la restauración. Define RPO/RTO reales y alerta si un backup no aparece. Crea el archivo de log con permiso 600 y configura logrotate.

Prueba una restauración periódica en una base aislada. Descarga un backup autorizado; con los servicios en mantenimiento y una base vacía de recuperación, puedes importar así (desde /opt/ghibli, root):

```bash
export APP_IMAGE="$(cat current-image)"
gunzip -c /ruta/backup.sql.gz | \
  docker compose -p ghibli --env-file .env -f compose.prod.yaml \
  exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" "$MYSQL_DATABASE"'
```

Ese comando reemplaza tablas del destino con el dump: úsalo solo en el destino de recuperación elegido, no sobre producción activa. Comprueba recuentos, usuarios, migración alembic_version y login. El dump incluye hashes de contraseñas y debe tratarse como dato confidencial. Conserva también secretos, revisión de código y configuración. Snapshots EBS ayudan, pero deben complementarse con restauraciones probadas.

Redis conserva revocaciones en volumen AOF. Si se pierde ese volumen, rota JWT_SECRET_KEY y recrea API antes de reabrir tráfico, para invalidar todos los tokens antiguos. La pérdida de caché Ghibli es tolerable; la pérdida de revocaciones requiere esta acción.

## 10. Monitoreo y mantenimiento

Revisa logs de API/Caddy, estado de contenedores, espacio EBS, memoria, CPU, errores 5xx, latencia y conexiones MySQL. Usa CloudWatch Agent si requieres métricas de memoria/disco y centralización de logs; su instalación/configuración no está incluida. Configura alarmas y notificación a un canal operativo de tu equipo.

Comandos útiles, con APP_IMAGE exportado como en el paso 7:

```bash
docker compose -p ghibli --env-file .env -f compose.prod.yaml logs --tail=100 api
docker compose -p ghibli --env-file .env -f compose.prod.yaml logs --tail=100 caddy
docker system df
df -h
```

Nunca registres Authorization, contraseñas ni cuerpos completos. No uses docker system prune --volumes en un host con datos. Habilita actualizaciones de seguridad del sistema y revisa cambios de dependencias en staging. Antes de cambiar versiones mayores de MySQL, planifica y prueba la migración de datos.

## 11. S3 para futuras imágenes (opcional, no implementado)

El API actual no guarda archivos y no requiere bucket de imágenes. Si agregas avatares: usa un bucket privado distinto del de backups, Block Public Access, cifrado y rol IAM sin claves estáticas. Guarda en MySQL solo la clave del objeto. Genera claves nuevas por usuario y versión, nunca rutas arbitrarias recibidas del cliente.

Añade validación de pertenencia, límite de tamaño, detección real del formato y decodificación/recodificación de la imagen antes de publicarla. Para subida directa usa POST prefirmado con límite content-length-range y un prefijo por usuario; posteriormente valida el objeto desde backend antes de asociarlo al perfil. Un Content-Type declarado por el cliente no basta.

Configura AWS_REGION y S3_IMAGES_BUCKET, permisos PutObject/GetObject/DeleteObject limitados al prefijo avatars/* y URLs prefirmadas de lectura con expiración corta. Si el SDK corre en el contenedor, planifica acceso seguro al rol de EC2/metadata o migra a ECS con task roles; no incrustes credenciales en Docker. Esta ampliación necesita endpoints, migración y pruebas adicionales, no se activa con solo variables de entorno.

## 12. Fallas frecuentes

- MySQL no está healthy: revisar contraseña, disco y logs. No borrar el volumen para resolver un problema en producción.
- API responde 503: verificar MySQL, Redis, migraciones y conectividad. La política falla cerrado si no se puede validar revocación.
- SSM no ve la instancia: verificar agente, instance profile, salida HTTPS y DNS.
- OIDC AccessDenied: verificar audience, sub exacto y environment production, incluyendo posible formato de IDs inmutables.
- Caddy no consigue certificado: revisar A/AAAA, puertos 80/443 y DNS.
- Ghibli 502/504: comprobar disponibilidad del proveedor y GHIBLI_BASE_URL; no quitar autorización para probarlo.
- ECR rechaza un tag existente: los tags son inmutables. Un reintento de build del mismo commit puede fallar al publicar; usa un nuevo commit o despliega el digest ya existente de forma controlada.
- Pipeline terminó sin confirmar SSM: inspeccionar Run Command antes de repetir, pues el comando remoto puede seguir ejecutándose.
