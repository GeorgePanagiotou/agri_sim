FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# /cache = disk cache for live POWER calls (mount a volume to keep it); /data/processed = parquet files (mounted read-only)
RUN useradd --create-home appuser && mkdir -p /cache /data/processed && chown appuser /cache
USER appuser
ENV DATA_DIR=/data/processed CACHE_DIR=/cache POWER_MODE=auto

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]