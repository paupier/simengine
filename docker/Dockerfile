FROM python:3.10-slim

LABEL maintainer="paupier"
LABEL description="Simantha OPC UA Digital Twin - Manufacturing Simulation"

WORKDIR /app

# Bake git commit SHA into the image for the UI header
COPY .git/HEAD .git/HEAD
COPY .git/refs .git/refs
COPY .git/packed-refs .git/packed-refs 2>/dev/null || true
RUN python3 -c "
import re, os
head = open('.git/HEAD').read().strip()
if re.fullmatch(r'[0-9a-f]{40}', head):
    sha = head[:7]
else:
    ref = head.split('ref: ')[1]
    try:
        sha = open(f'.git/{ref}').read().strip()[:7]
    except FileNotFoundError:
        sha = open('.git/packed-refs').read()
        sha = next((l.split()[0][:7] for l in sha.splitlines() if ref in l), 'dev')
open('/app/BUILD_SHA', 'w').write(sha)
" && rm -rf .git

# Install core simulation dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Docker-specific dependencies (Flask web UI + historian backends)
COPY docker/webui/requirements.txt /tmp/webui-requirements.txt
RUN pip install --no-cache-dir -r /tmp/webui-requirements.txt \
    && pip install --no-cache-dir influxdb-client>=1.30.0 neo4j>=5.0.0 \
    && rm /tmp/webui-requirements.txt

# Copy application source
COPY src/ /app/src/
COPY config/ /app/config/

# Copy web UI and Telegraf config generator
COPY docker/webui/ /app/docker/webui/
COPY docker/telegraf/generate_telegraf_conf.py /app/docker/telegraf/generate_telegraf_conf.py

# Copy analysis tools (report_engine, analyze_historian)
COPY tools/ /app/tools/

# Copy Grafana dashboards (for volume mount reference)
COPY docker/grafana/dashboards/ /app/grafana/dashboards/

# Copy NeoDash dashboard for auto-seeding
COPY docker/neo4j/dashboards/ /app/docker/neo4j/dashboards/

# Copy entrypoint
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

# Create output directories
RUN mkdir -p /app/results/historian

# Expose ports: 8080 = Web UI, 4840 = OPC UA
EXPOSE 8080 4840

# Healthcheck via Flask web UI
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/status')" || exit 1

ENTRYPOINT ["bash", "/app/docker/entrypoint.sh"]
