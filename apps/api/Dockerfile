FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY apps/api /app
COPY packages/sim /opt/packages/sim
ENV PYTHONPATH=/app:/opt/packages/sim

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
