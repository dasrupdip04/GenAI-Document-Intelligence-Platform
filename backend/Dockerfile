FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

ENV GEMINI_API_KEY="" \
    GEMINI_MODEL=gemini-2.0-flash \
    GEMINI_EMBEDDING_MODEL=gemini-embedding-001 \
    EMBEDDING_DIMENSIONS=768

COPY . .

RUN mkdir -p /app/storage/documents

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
