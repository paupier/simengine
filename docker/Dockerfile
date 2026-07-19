# Multi-stage build (parent performance spec D2): builder installs into a
# venv; the final image carries only the venv + sources. Plugin extras via
# --build-arg EXTRAS=historian-influx,historian-neo4j,sparkplug
FROM python:3.10-slim AS builder

ARG EXTRAS=""

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && if [ -n "$EXTRAS" ]; then \
         /opt/venv/bin/pip install --no-cache-dir ".[${EXTRAS}]"; \
       else \
         /opt/venv/bin/pip install --no-cache-dir .; \
       fi

FROM python:3.10-slim

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN useradd --create-home simengine
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY config ./config

USER simengine

EXPOSE 8080 4840

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz', timeout=3)"

CMD ["python", "-m", "simengine"]
