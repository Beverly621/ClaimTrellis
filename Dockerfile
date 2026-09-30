FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLAIM_TRELLIS_HOST=0.0.0.0 \
    CLAIM_TRELLIS_PORT=8000 \
    CLAIM_TRELLIS_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
COPY web ./web
COPY migrations ./migrations
RUN python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 claimtrellis && mkdir -p /data && chown claimtrellis:claimtrellis /data
USER claimtrellis

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["claim-trellis", "serve"]
