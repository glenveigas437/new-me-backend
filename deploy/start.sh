#!/bin/sh
set -eu
: "${DATABASE_URL:?Set your Supabase Session pooler DATABASE_URL}"
: "${SECRET_KEY:?Set a private production SECRET_KEY}"
case "$DATABASE_URL" in
  postgres://*|postgresql://*) ;;
  *) echo "Production requires a persistent PostgreSQL DATABASE_URL." >&2; exit 1 ;;
esac
cd /app
# Free Render services have no pre-deploy command. Single-instance startup
# applies migrations before accepting traffic; failed migrations stop startup.
python manage.py migrate --noinput
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -
