FROM python:3-alpine

LABEL Name=tg-ai-blocker Version=0.0.1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache

COPY .env .
COPY app .

# Test imports during build
RUN python -c "import main"

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "warning"]
