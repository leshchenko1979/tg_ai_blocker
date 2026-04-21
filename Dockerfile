# Stage 1: builder
FROM python:3-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config gcc libffi-dev libssl-dev cargo protobuf-compiler && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src/app ./app/

RUN set -e; pip install --no-cache-dir uv && \
    uv pip install --system -r pyproject.toml

# Stage 2: runner
FROM python:3-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY pyproject.toml ./
COPY --chown=appuser:appuser PRD.md config.yaml ./
COPY src/app ./app/

RUN groupadd -f -g 1000 appuser; \
    useradd -s /bin/sh -u 1000 -M -g 1000 appuser; \
    mkdir -p logs && chown -R appuser:appuser /app

USER appuser

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=1 \
  CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "-m", "app.main"]
