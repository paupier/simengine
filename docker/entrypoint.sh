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

# Step 3: Start the Flask web UI (manages simulation subprocess)
echo "[Entrypoint] Starting Web UI on port ${WEBUI_PORT:-8080}..."
echo "[Entrypoint] OPC UA will be available on port 4840 after simulation starts"
echo "================================================"

exec python /app/docker/webui/app.py
