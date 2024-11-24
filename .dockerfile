FROM python:3-alpine

LABEL Name=tg-ai-blocker Version=0.0.1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache

COPY .env PRD.md config.yaml ./
COPY src/app ./app

# Test imports during build
RUN PYTHONPATH=/app python -c "from app import main"

COPY aiogram_types.cache .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "warning"]
