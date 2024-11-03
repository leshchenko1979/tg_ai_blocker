FROM python:3-alpine

LABEL Name=tg-ai-blocker Version=0.0.1

COPY requirements.txt /

RUN pip install -r requirements.txt --no-cache

COPY .env /
COPY app ./app

EXPOSE 5000:8080

WORKDIR /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
