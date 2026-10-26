#!/usr/bin/env bash
# Programar desde root (systemd/cron). Nunca exponer backups públicamente.
set -Eeuo pipefail
umask 077
cd /opt/ghibli
bucket="${1:?Private S3 backup bucket required}"
export APP_IMAGE="$(cat current-image)"
file="$(mktemp /tmp/ghibli-backup.XXXXXX.sql.gz)"
trap 'rm -f "$file"' EXIT
# Solo DML durante este backup; no solapar con migraciones DDL.
exec 9>/opt/ghibli/deploy.lock
flock 9
docker compose -p ghibli --env-file .env -f compose.prod.yaml exec -T mysql \
  sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump -u "$MYSQL_USER" --single-transaction --no-tablespaces --set-gtid-purged=OFF "$MYSQL_DATABASE"' | gzip > "$file"
aws s3 cp "$file" "s3://$bucket/mysql/$(date -u +%Y%m%dT%H%M%SZ).sql.gz" --sse AES256 --only-show-errors
