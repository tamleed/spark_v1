FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY gateway /app/gateway
COPY worker /app/worker
COPY configs /app/configs
COPY scripts /app/scripts
ENV PYTHONPATH=/app/gateway
