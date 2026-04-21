# rebuild trigger
FROM python:3-alpine

RUN apk add --no-cache curl libgcc

WORKDIR /app

COPY pyproject.toml ./
RUN mkdir -p src && touch src/__init__.py
COPY src/app ./app/

# Install dependencies via uv
RUN set -e; pip install --no-cache-dir uv; \
    uv pip install --system --no-cache -r pyproject.toml; \
    pip uninstall -y uv; \
    rm -rf /root/.cache/uv

# Non-root user (appuser, uid 1000)
RUN addgroup -g 1000 appuser && \
    adduser -D -s /bin/sh -u 1000 -G appuser appuser

RUN mkdir -p logs && chown -R appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser PRD.md config.yaml ./

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=1 \
  CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "-m", "app.main"]