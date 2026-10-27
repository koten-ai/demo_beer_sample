FROM python:3.12-slim

WORKDIR /app

# Secrets and the synced catalog stay on the host. Do not copy .env or data/.
COPY requirements.txt ./
COPY main.py config.json ./
COPY static ./static

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8090
ENV HOST=0.0.0.0
ENV ZEUS_CLIENT_CHAT_REQUESTS_DIR=/app/data/chat_requests

EXPOSE 8090
CMD ["python", "main.py"]
