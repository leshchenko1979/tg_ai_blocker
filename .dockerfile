FROM python:3.13-alpine

LABEL Name=tg-ai-blocker Version=0.0.1

WORKDIR /app

COPY pyproject.toml ./
RUN set -eux; \
    pip install --no-cache-dir uv; \
    uv pip install --system --no-cache -r pyproject.toml; \
    pip uninstall -y uv; \
    rm -rf /root/.cache/uv

COPY .env PRD.md config.yaml ./

COPY src/app ./app

EXPOSE 8080

CMD ["python", "-m", "app.main"]
