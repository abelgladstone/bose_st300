FROM python:3.12-slim

# gunicorn tuning lives here so the single-worker constraint is visible at runtime.
# One worker (the WebSocket bridge is in-process); threads carry concurrent SSE clients.
ENV PYTHONUNBUFFERED=1 \
    GUNICORN_CMD_ARGS="--workers 1 --threads 24 --worker-class gthread --timeout 120 --graceful-timeout 30 --bind 0.0.0.0:5001"

WORKDIR /app

# Dependencies first for layer caching. Installed straight into system site-packages
# via pip -- no uv/venv needed in the image.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "flask>=3.0" "requests>=2.31" "zeroconf>=0.132" \
        "websocket-client>=1.7" "gunicorn>=21.2"

COPY soundtouch/ ./soundtouch/
COPY views/ ./views/
COPY wsgi.py config.toml ./

EXPOSE 5001

# Liveness only; never probes the speaker (a sleeping speaker must not fail the check).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5001/healthz',timeout=4).status==200 else 1)"

CMD ["gunicorn", "wsgi:app"]
