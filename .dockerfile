FROM python:3.13-alpine

LABEL Name=tg-ai-blocker Version=0.0.1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

COPY .env PRD.md config.yaml ./
COPY src/app ./app

# Test imports during build
# RUN PYTHONPATH=/app python -c "from app import main"

EXPOSE 8080

CMD ["python", "-m", "app.main"]
