"""
Flask Web UI for Simantha OPC UA Digital Twin.

Manages the simulation subprocess and provides a browser-based interface
for scenario selection, simulation control, and live KPI monitoring.
"""
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from io import StringIO
from pathlib import Path

import re

from ruamel.yaml import YAML

from flask import Flask, jsonify, render_template, request

_ryaml = YAML()
_ryaml.preserve_quotes = True
_ryaml.indent(mapping=2, sequence=4, offset=2)


def _find_scenario_span(text, name):
    """Find the start and end character positions of a scenario block in YAML text.

    Returns (start, end) where text[start:end] is the full scenario block
    including its key line. Returns (None, None) if not found.
    """
    # Match the scenario key at the start of a line (top-level, no indent)
    pattern = re.compile(rf'^{re.escape(name)}:\s*(?:#.*)?\n', re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None, None

    start = match.start()

    # Find the end: next top-level key (non-whitespace at column 0 followed by colon)
    # or end of file
    rest = text[match.end():]
    end_pattern = re.compile(r'^\S', re.MULTILINE)
    end_match = end_pattern.search(rest)
    if end_match:
        end = match.end() + end_match.start()
    else:
        end = len(text)

    return start, end


def _render_scenario_yaml(name, data):
    """Render a single scenario as YAML text with correct indentation."""
    ry = YAML()
    ry.indent(mapping=2, sequence=4, offset=2)
    buf = StringIO()
    ry.dump({name: data}, buf)
    return buf.getvalue()


def _save_scenario_to_file(cfg_path, name, data):
    """Save a scenario to the YAML file using text-level surgery.

    Only the target scenario block is replaced; all other content
    (comments, formatting, other scenarios) is preserved byte-for-byte.
    """
    with open(cfg_path, "r") as f:
        original_text = f.read()

    new_block = _render_scenario_yaml(name, data)

    start, end = _find_scenario_span(original_text, name)
    if start is not None:
        # Replace existing scenario block
        # Ensure there's a blank line before the next scenario
        modified = original_text[:start] + new_block
        remaining = original_text[end:]
        if remaining and not remaining.startswith("\n"):
            modified += "\n"
        modified += remaining
    else:
        # Append new scenario at end of file
        if not original_text.endswith("\n"):
            original_text += "\n"
        modified = original_text + "\n" + new_block

    with open(cfg_path, "w") as f:
        f.write(modified)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.json.sort_keys = False

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
sim_process = None
sim_scenario = None
sim_start_time = None
sim_log = deque(maxlen=200)  # Ring buffer for stdout capture
sim_lock = threading.Lock()

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent  # docker/webui/ → project root
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

CONFIG_PATH = Path(os.environ.get(
    "SIMANTHA_CONFIG_PATH",
    str(_PROJECT_ROOT / "config" / "line_models.yaml")
))
ORIGINAL_CONFIG_PATH = Path(os.environ.get(
    "SIMANTHA_ORIGINAL_CONFIG_PATH",
    str(_PROJECT_ROOT / "config" / "line_models.yaml")
))

OPCUA_SERVER_SCRIPT = os.environ.get(
    "SIMANTHA_SERVER_SCRIPT",
    str(_PROJECT_ROOT / "src" / "opcua_server.py")
)

OPCUA_ENDPOINT = os.environ.get(
    "SIMANTHA_OPCUA_ENDPOINT",
    "opc.tcp://localhost:4840/simantha/"
)

# OPC UA client (lazy-connected)
_opcua_client = None


# ---------------------------------------------------------------------------
# Scenario listing
# ---------------------------------------------------------------------------
def list_scenarios():
    """Parse line_models.yaml and return scenario metadata."""
    config_path = ORIGINAL_CONFIG_PATH if ORIGINAL_CONFIG_PATH.exists() else CONFIG_PATH
    with open(config_path, "r") as f:
        all_configs = _ryaml.load(f)

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

        cmd = ["python", OPCUA_SERVER_SCRIPT, "--scenario", scenario]
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
    """Gracefully stop the simulation subprocess."""
    global sim_process, sim_scenario, sim_start_time, _opcua_client

    _disconnect_opcua()

    if sim_process and sim_process.poll() is None:
        try:
            if sys.platform == "win32":
                sim_process.terminate()
            else:
                sim_process.send_signal(signal.SIGINT)
            sim_process.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired, ValueError):
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
        client = Client(OPCUA_ENDPOINT)
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

        # Read machine states dynamically
        machines = {}
        for i in range(1, 20):  # Up to 19 machines
            try:
                machine = line1.get_child([f"2:Machine{i}"])
                state = machine.get_child(["2:State"]).get_value()
                partcount = machine.get_child(["2:PartCount"]).get_value()
                target_ppm = machine.get_child(["2:TargetPPM"]).get_value()
                actual_ppm = machine.get_child(["2:ActualPPM"]).get_value()
                m_data = {
                    "state": state, "partcount": partcount,
                    "target_ppm": target_ppm, "actual_ppm": actual_ppm,
                }
                # OEE (always present)
                try:
                    oee_node = machine.get_child(["2:OEE"])
                    m_data["availability"] = oee_node.get_child(["2:Availability"]).get_value()
                    m_data["performance"] = oee_node.get_child(["2:Performance"]).get_value()
                    m_data["quality"] = oee_node.get_child(["2:Quality"]).get_value()
                    m_data["oee"] = oee_node.get_child(["2:OEE"]).get_value()
                except Exception:
                    pass
                # SPC Capability (optional)
                try:
                    cap_node = machine.get_child(["2:SPC", "2:Capability"])
                    m_data["cp"] = cap_node.get_child(["2:Cp"]).get_value()
                    m_data["cpk"] = cap_node.get_child(["2:Cpk"]).get_value()
                except Exception:
                    pass
                # Active failure mode (optional)
                try:
                    fm_node = machine.get_child(["2:FailureModes"])
                    m_data["active_failure"] = fm_node.get_child(["2:ActiveFailureMode"]).get_value()
                except Exception:
                    pass
                machines[f"Machine{i}"] = m_data
            except Exception:
                break

        # Line-level KPIs
        line_oee = {}
        try:
            oee_node = line1.get_child(["2:LineKPIs", "2:LineOEE"])
            line_oee["availability"] = oee_node.get_child(["2:Availability"]).get_value()
            line_oee["performance"] = oee_node.get_child(["2:Performance"]).get_value()
            line_oee["quality"] = oee_node.get_child(["2:Quality"]).get_value()
            line_oee["oee"] = oee_node.get_child(["2:OEE"]).get_value()
        except Exception:
            pass
        line_kpis = {}
        try:
            kpi_node = line1.get_child(["2:LineKPIs"])
            line_kpis["total_scrap"] = kpi_node.get_child(["2:TotalScrap"]).get_value()
            line_kpis["scrap_rate"] = kpi_node.get_child(["2:ScrapRate"]).get_value()
        except Exception:
            pass

        # Shift info (optional)
        shift_info = {}
        try:
            shift_node = line1.get_child(["2:Shift", "2:CurrentShift"])
            shift_info["name"] = shift_node.get_child(["2:CurrentShiftName"]).get_value()
            shift_info["elapsed"] = shift_node.get_child(["2:ShiftElapsedTime"]).get_value()
            shift_info["duration"] = shift_node.get_child(["2:ShiftDuration"]).get_value()
        except Exception:
            pass

        return {
            "sim_time": sim_time,
            "throughput": throughput,
            "pause_line": pause_line,
            "interarrival_time": interarrival,
            "machines": machines,
            "line_oee": line_oee,
            "line_kpis": line_kpis,
            "shift": shift_info,
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
# Config editor routes
# ---------------------------------------------------------------------------
def _get_config_file_path():
    """Return the writable config file path."""
    return ORIGINAL_CONFIG_PATH if ORIGINAL_CONFIG_PATH.exists() else CONFIG_PATH


@app.route("/config")
def config_editor():
    """Render the scenario config editor page."""
    return render_template("config.html")


@app.route("/api/scenario/<name>")
def api_get_scenario(name):
    """Return full config for a single scenario."""
    cfg_path = _get_config_file_path()
    with open(cfg_path, "r") as f:
        all_configs = _ryaml.load(f)
    if name not in all_configs:
        return jsonify({"error": f"Scenario '{name}' not found"}), 404
    return jsonify(all_configs[name])


@app.route("/api/scenario/<name>", methods=["PUT"])
def api_update_scenario(name):
    """Update an existing scenario config."""
    cfg_path = _get_config_file_path()
    with open(cfg_path, "r") as f:
        all_configs = _ryaml.load(f)
    if name not in all_configs:
        return jsonify({"error": f"Scenario '{name}' not found"}), 404

    data = request.get_json(force=True)

    # Validate
    try:
        from config_loader import validate_serial_topology
        validate_serial_topology(data)
    except Exception as e:
        return jsonify({"error": f"Validation failed: {e}"}), 400

    _save_scenario_to_file(cfg_path, name, data)
    return jsonify({"status": "ok", "scenario": name})


@app.route("/api/scenario", methods=["POST"])
def api_create_scenario():
    """Create a new scenario."""
    data = request.get_json(force=True)
    name = data.pop("_name", None)
    if not name:
        return jsonify({"error": "Missing '_name' field"}), 400

    cfg_path = _get_config_file_path()
    with open(cfg_path, "r") as f:
        all_configs = _ryaml.load(f)
    if name in all_configs:
        return jsonify({"error": f"Scenario '{name}' already exists"}), 409

    # Validate
    try:
        from config_loader import validate_serial_topology
        validate_serial_topology(data)
    except Exception as e:
        return jsonify({"error": f"Validation failed: {e}"}), 400

    _save_scenario_to_file(cfg_path, name, data)
    return jsonify({"status": "created", "scenario": name}), 201


@app.route("/api/scenario/<name>/yaml")
def api_scenario_yaml(name):
    """Return scenario config as YAML text (for preview)."""
    cfg_path = _get_config_file_path()
    with open(cfg_path, "r") as f:
        all_configs = _ryaml.load(f)
    if name not in all_configs:
        return jsonify({"error": f"Scenario '{name}' not found"}), 404
    buf = StringIO()
    _ryaml.dump({name: all_configs[name]}, buf)
    return jsonify({"yaml": buf.getvalue()})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("WEBUI_PORT", 8080))
    print(f"[WebUI] Starting on port {port}")
    print(f"[WebUI] Config: {CONFIG_PATH}")
    app.jinja_env.auto_reload = True
    app.run(host="0.0.0.0", port=port, debug=False)
