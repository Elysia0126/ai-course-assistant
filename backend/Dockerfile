# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the default local embedding model into the image so the first upload doesn't wait on a download.
# Build with --build-arg PRELOAD_EMBEDDING_MODEL= to skip (e.g. when using EMBEDDING_PROVIDER=openai).
ARG PRELOAD_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN if [ -n "$PRELOAD_EMBEDDING_MODEL" ]; then \
      python -c "from fastembed import TextEmbedding; TextEmbedding('$PRELOAD_EMBEDDING_MODEL', cache_dir='/app/data/models')"; \
    fi

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/uploads /app/data/outbox \
    && chown -R appuser:appuser /app/data
USER appuser

# Migrations run once, explicitly, before the server starts.
ENV AUTO_MIGRATE=false
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=4)"

# No --proxy-headers: the app decides itself which X-Forwarded-For to believe (APP_API_TOKEN / TRUSTED_PROXY_IPS).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers"]
