#!/bin/sh
set -e

VT_HOST="${POSTGRES_HOST:-postgresfadil}"
VT_PORT="${POSTGRES_PORT:-5434}"

echo "Veritabanı bekleniyor (${VT_HOST}:${VT_PORT})..."
deneme=0
until pg_isready -h "$VT_HOST" -p "$VT_PORT" -U "$POSTGRES_USER" >/dev/null 2>&1; do
  deneme=$((deneme + 1))
  if [ "$deneme" -gt 60 ]; then
    echo "Veritabanına 60 saniyede bağlanılamadı, çıkılıyor." >&2
    exit 1
  fi
  sleep 1
done

# Migration'ları uygular ve eksik başlangıç verisini tamamlar.
# Var olan kayıtlara dokunmaz; her açılışta güvenle çalışır.
python manage.py kurulum

echo "Statik dosyalar toplanıyor..."
python manage.py collectstatic --noinput

exec "$@"
