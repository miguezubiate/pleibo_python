#!/usr/bin/env bash
# Ejecutado por SSM como root; artefacto ECR identificado por digest inmutable.
set -Eeuo pipefail
umask 077
cd /opt/ghibli
exec 9>/opt/ghibli/deploy.lock
flock -n 9 || { echo 'Otro despliegue está en curso'; exit 1; }
image="${1:?image@sha256 required}"
region="${2:?AWS region required}"
[[ "$image" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9/_-]+@sha256:[a-f0-9]{64}$ ]] || exit 2
[[ "$region" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]] || exit 2
registry="${image%%/*}"
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"
export APP_IMAGE="$image"
compose() { docker compose --project-name ghibli --env-file .env -f compose.prod.yaml "$@"; }
compose pull api migrate
compose up -d --wait --wait-timeout 180 mysql redis
# No ejecutar migraciones con cada worker. Solo este proceso las aplica.
compose run --rm --no-deps migrate
previous=""
[[ ! -f current-image ]] || previous="$(cat current-image)"
rollback() {
    echo 'Falló el arranque; intentando volver a imagen anterior (sin revertir esquema).'
    if [[ -n "$previous" ]]; then
        export APP_IMAGE="$previous"
        compose up -d --no-deps --wait --wait-timeout 120 api
    fi
    exit 1
}
compose up -d --no-deps --wait --wait-timeout 120 api || rollback
compose up -d caddy
curl --fail --silent --show-error http://127.0.0.1:8000/health/ready || rollback
printf '%s
' "$previous" > previous-image
printf '%s
' "$image" > current-image
printf 'Despliegue correcto: %s
' "$image"
