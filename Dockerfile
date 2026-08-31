FROM python:3.11-slim

WORKDIR /app

# librerie di sistema richieste da PyMuPDF/shapely per il rendering PDF e la geometria
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

ENV PYTHONUNBUFFERED=1 \
    COMPUTO_DATA_DIR=/data

RUN mkdir -p /data/uploads /data/output /data/prezzari

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
