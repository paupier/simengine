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
    PYTHONUNBUFFERED=1 \
    SIMENGINE_CONFIG_PATH=/app/config/scenarios.yaml \
    SIMENGINE_RECIPE_PATH=/app/config/recipes

RUN useradd --create-home simengine
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
# config and results are simengine-owned so the non-root runtime user can write:
# scenario/recipe edits via the UI/REST rewrite /app/config, and the CSV
# historian writes under /app/results. A named volume mounted at either path
# seeds its ownership from these dirs on first run.
COPY --chown=simengine:simengine config ./config
RUN mkdir -p /app/results && chown simengine:simengine /app/results

USER simengine

EXPOSE 8080 4840

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz', timeout=3)"

CMD ["python", "-m", "simengine"]
