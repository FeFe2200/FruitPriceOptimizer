#!/bin/sh
set -eu

BACKUP=/backups/latest.dump

if [ ! -s "$BACKUP" ]; then
  echo "db-init: latest.dump 없음 — 빈 DB로 시작합니다."
  exit 0
fi

has_schema="$(psql -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "SELECT CASE WHEN to_regclass('public.users') IS NULL THEN 'no' ELSE 'yes' END")"

if [ "$has_schema" = "yes" ]; then
  echo "db-init: 기존 스키마가 있어 복원을 건너뜁니다."
  exit 0
fi

echo "db-init: /backups/latest.dump 복원 중..."
pg_restore \
  --host=db \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  "$BACKUP"
echo "db-init: 복원 완료"
