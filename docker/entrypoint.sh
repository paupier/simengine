#!/bin/bash
set -e

echo "================================================"
echo "  Simantha OPC UA Digital Twin"
echo "  Docker Deployment"
echo "================================================"

# Step 1: Generate runtime config with InfluxDB enabled for all scenarios
echo "[Entrypoint] Injecting historian config..."
python /app/docker/webui/inject_historian.py

# Step 2: Set Docker-specific environment variables
export SIMANTHA_CONFIG_PATH="/app/config/line_models_runtime.yaml"
export SIMANTHA_ORIGINAL_CONFIG_PATH="/app/config/line_models.yaml"
export SIMANTHA_SERVER_SCRIPT="/app/src/opcua_server.py"
export TELEGRAF_CONF_PATH="/etc/telegraf/telegraf.conf"

# Step 3: Generate initial Telegraf config for default scenario
echo "[Entrypoint] Generating Telegraf config for ${DEFAULT_SCENARIO:-full_feature_line}..."
python /app/docker/telegraf/generate_telegraf_conf.py \
    --config /app/config/line_models_runtime.yaml \
    --scenario "${DEFAULT_SCENARIO:-full_feature_line}" \
    --output /etc/telegraf/telegraf.conf || \
    echo "[Entrypoint] Warning: Telegraf config generation failed (non-fatal)"

# Step 4: Start the Flask web UI (manages simulation subprocess)
echo "[Entrypoint] Starting Web UI on port ${WEBUI_PORT:-8080}..."
echo "[Entrypoint] OPC UA will be available on port 4840 after simulation starts"
echo "================================================"

exec python /app/docker/webui/app.py
