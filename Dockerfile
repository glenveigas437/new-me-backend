FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN test -f staticfiles/index.html \
    && DEBUG=False SECRET_KEY=build-only-not-runtime-key-123456789012345678901234567890 DATABASE_URL=sqlite:////tmp/build.sqlite3 python manage.py collectstatic --noinput \
    && useradd --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 10000
CMD ["sh", "/app/deploy/start.sh"]
