FROM python:3.10-slim

LABEL maintainer="paupier"
LABEL description="Simantha OPC UA Digital Twin - Manufacturing Simulation"

WORKDIR /app

# Install core simulation dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Docker-specific dependencies (Flask web UI + historian backends)
COPY docker/webui/requirements.txt /tmp/webui-requirements.txt
RUN pip install --no-cache-dir -r /tmp/webui-requirements.txt \
    && pip install --no-cache-dir influxdb-client>=1.30.0 \
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
