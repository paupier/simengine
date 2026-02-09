"""
Flask Web UI for Simantha OPC UA Digital Twin.

Manages the simulation subprocess and provides a browser-based interface
for scenario selection, simulation control, and live KPI monitoring.
"""
import os
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
sim_process = None
sim_scenario = None
sim_start_time = None
sim_log = deque(maxlen=200)  # Ring buffer for stdout capture
sim_lock = threading.Lock()

CONFIG_PATH = Path(os.environ.get(
    "SIMANTHA_CONFIG_PATH",
    "/app/config/line_models_runtime.yaml"
))
ORIGINAL_CONFIG_PATH = Path("/app/config/line_models.yaml")

# OPC UA client (lazy-connected)
_opcua_client = None


# ---------------------------------------------------------------------------
# Scenario listing
# ---------------------------------------------------------------------------
def list_scenarios():
    """Parse line_models.yaml and return scenario metadata."""
    config_path = ORIGINAL_CONFIG_PATH if ORIGINAL_CONFIG_PATH.exists() else CONFIG_PATH
    with open(config_path, "r") as f:
        all_configs = yaml.safe_load(f)

    scenarios = {}
    for key, cfg in all_configs.items():
        if not isinstance(cfg, dict):
            continue
        machines = cfg.get("machines", [])
        buffers = cfg.get("buffers", [])
        desc = cfg.get("description", "")
        features = []
        if cfg.get("maintainer", {}).get("enabled", False):
            features.append("maintenance")
        if cfg.get("shifts"):
            features.append("shifts")
        if cfg.get("historian"):
            features.append("historian")
        if cfg.get("scrap_sinks"):
            features.append("scrap/rework")
        for m in machines:
            if m.get("quality_routing", {}).get("enabled", False):
                features.append("quality routing")
                break
        for m in machines:
            if m.get("enable_advanced_failures", False):
                features.append("advanced failures")
                break
        for m in machines:
            if m.get("spc"):
                features.append("SPC")
                break

        scenarios[key] = {
            "description": desc,
            "machines": len(machines),
            "buffers": len(buffers),
            "features": list(set(features)),
        }
    return scenarios


# ---------------------------------------------------------------------------
# Subprocess management
# ---------------------------------------------------------------------------
def _capture_logs():
    """Background thread: read subprocess stdout into ring buffer."""
    global sim_process
    proc = sim_process
    if proc is None:
        return
    try:
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            sim_log.append(line.rstrip("\n"))
    except (ValueError, OSError):
        pass


def start_simulation(scenario, seed=None):
    """Spawn opcua_server.py as a subprocess."""
    global sim_process, sim_scenario, sim_start_time, _opcua_client

    with sim_lock:
        stop_simulation()

        cmd = ["python", "/app/src/opcua_server.py", "--scenario", scenario]
        if seed is not None:
            cmd += ["--seed", str(seed)]

        env = os.environ.copy()
        env["SIMANTHA_CONFIG_PATH"] = str(CONFIG_PATH)

        sim_log.clear()
        sim_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        sim_scenario = scenario
        sim_start_time = time.time()

        # Disconnect OPC UA client (will reconnect lazily)
        _disconnect_opcua()

        # Background log capture thread
        t = threading.Thread(target=_capture_logs, daemon=True)
        t.start()


def stop_simulation():
    """Send SIGINT for graceful shutdown (flushes historians)."""
    global sim_process, sim_scenario, sim_start_time, _opcua_client

    _disconnect_opcua()

    if sim_process and sim_process.poll() is None:
        try:
            sim_process.send_signal(signal.SIGINT)
            sim_process.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            sim_process.kill()
            sim_process.wait(timeout=5)
    sim_process = None
    sim_scenario = None
    sim_start_time = None


# ---------------------------------------------------------------------------
# OPC UA client helpers
# ---------------------------------------------------------------------------
def _get_opcua_client():
    """Lazy-connect OPC UA client to local simulation server."""
    global _opcua_client
    if _opcua_client is not None:
        return _opcua_client
    try:
        from opcua import Client
        client = Client("opc.tcp://localhost:4840/simantha/")
        client.connect()
        _opcua_client = client
        return client
    except Exception:
        return None


def _disconnect_opcua():
    """Disconnect OPC UA client."""
    global _opcua_client
    if _opcua_client is not None:
        try:
            _opcua_client.disconnect()
        except Exception:
            pass
        _opcua_client = None


def _read_opcua_values():
    """Read key OPC UA variables for the web dashboard."""
    client = _get_opcua_client()
    if client is None:
        return None
    try:
        root = client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        system = line1.get_child(["2:System"])
        sim_time = system.get_child(["2:SimTime"]).get_value()
        throughput = system.get_child(["2:Throughput"]).get_value()

        controls = system.get_child(["2:Controls"])
        pause_line = controls.get_child(["2:cmdPauseLine"]).get_value()
        interarrival = controls.get_child(["2:setInterarrivalTime"]).get_value()

        # Read station states dynamically
        stations = {}
        for i in range(1, 20):  # Up to 19 stations
            try:
                station = line1.get_child([f"2:Station{i}"])
                state = station.get_child(["2:State"]).get_value()
                partcount = station.get_child(["2:PartCount"]).get_value()
                stations[f"Station{i}"] = {"state": state, "partcount": partcount}
            except Exception:
                break

        return {
            "sim_time": sim_time,
            "throughput": throughput,
            "pause_line": pause_line,
            "interarrival_time": interarrival,
            "stations": stations,
        }
    except Exception:
        _disconnect_opcua()
        return None


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Main web UI page."""
    return render_template("index.html")


@app.route("/api/scenarios")
def api_scenarios():
    """List all available scenarios."""
    return jsonify(list_scenarios())


@app.route("/api/status")
def api_status():
    """Current simulation status."""
    running = sim_process is not None and sim_process.poll() is None
    uptime = None
    if running and sim_start_time:
        uptime = round(time.time() - sim_start_time, 1)

    result = {
        "running": running,
        "scenario": sim_scenario,
        "uptime_seconds": uptime,
        "pid": sim_process.pid if sim_process else None,
    }

    # Include OPC UA values if running
    if running:
        opcua_vals = _read_opcua_values()
        if opcua_vals:
            result["opcua"] = opcua_vals

    return jsonify(result)


@app.route("/api/start", methods=["POST"])
def api_start():
    """Start simulation with selected scenario."""
    data = request.get_json(force=True) if request.data else {}
    scenario = data.get("scenario", "balanced_line")
    seed = data.get("seed")

    # Validate scenario exists
    scenarios = list_scenarios()
    if scenario not in scenarios:
        return jsonify({"error": f"Unknown scenario: {scenario}"}), 400

    if seed is not None:
        try:
            seed = int(seed)
        except (ValueError, TypeError):
            return jsonify({"error": "seed must be an integer"}), 400

    start_simulation(scenario, seed)
    return jsonify({"status": "started", "scenario": scenario, "seed": seed})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Stop running simulation."""
    with sim_lock:
        if sim_process is None or sim_process.poll() is not None:
            return jsonify({"status": "not_running"})
        stop_simulation()
    return jsonify({"status": "stopped"})


@app.route("/api/logs")
def api_logs():
    """Return recent simulation log lines."""
    return jsonify({"lines": list(sim_log)})


@app.route("/api/control", methods=["POST"])
def api_control():
    """Write OPC UA control variables (pause, interarrival time)."""
    if sim_process is None or sim_process.poll() is not None:
        return jsonify({"error": "Simulation not running"}), 400

    data = request.get_json(force=True) if request.data else {}
    client = _get_opcua_client()
    if client is None:
        return jsonify({"error": "Cannot connect to OPC UA server"}), 503

    try:
        root = client.get_objects_node()
        controls = root.get_child(["2:Line1", "2:System", "2:Controls"])
        result = {}

        if "pause_line" in data:
            val = bool(data["pause_line"])
            controls.get_child(["2:cmdPauseLine"]).set_value(val)
            result["pause_line"] = val

        if "interarrival_time" in data:
            val = float(data["interarrival_time"])
            controls.get_child(["2:setInterarrivalTime"]).set_value(val)
            result["interarrival_time"] = val

        return jsonify({"status": "ok", "written": result})
    except Exception as e:
        _disconnect_opcua()
        return jsonify({"error": str(e)}), 500


@app.route("/api/opcua/read")
def api_opcua_read():
    """Read key OPC UA values."""
    if sim_process is None or sim_process.poll() is not None:
        return jsonify({"error": "Simulation not running"}), 400

    values = _read_opcua_values()
    if values is None:
        return jsonify({"error": "Cannot read OPC UA values"}), 503
    return jsonify(values)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("WEBUI_PORT", 8080))
    print(f"[WebUI] Starting on port {port}")
    print(f"[WebUI] Config: {CONFIG_PATH}")
    app.run(host="0.0.0.0", port=port, debug=False)
