"""
Flask Web UI for Simantha OPC UA Digital Twin.

Manages the simulation subprocess and provides a browser-based interface
for scenario selection, simulation control, and live KPI monitoring.
"""
import json
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

from datetime import datetime as dt
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

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
sim_recipe = None
sim_start_time = None
sim_run_id = None
sim_seed = None
sim_interarrival_time = None
sim_log = deque(maxlen=200)  # Ring buffer for stdout capture
sim_lock = threading.Lock()

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent  # docker/webui/ → project root
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

CONFIG_PATH = Path(os.environ.get(
    "SIMANTHA_CONFIG_PATH",
    str(_PROJECT_ROOT / "config" / "line_models.yaml")
))
ORIGINAL_CONFIG_PATH = Path(os.environ.get(
    "SIMANTHA_ORIGINAL_CONFIG_PATH",
    str(_PROJECT_ROOT / "config" / "line_models.yaml")
))

RECIPES_DIR = Path(os.environ.get(
    "SIMANTHA_RECIPES_DIR",
    str(_PROJECT_ROOT / "config" / "recipes")
))

OPCUA_SERVER_SCRIPT = os.environ.get(
    "SIMANTHA_SERVER_SCRIPT",
    str(_PROJECT_ROOT / "src" / "opcua_server.py")
)

OPCUA_ENDPOINT = os.environ.get(
    "SIMANTHA_OPCUA_ENDPOINT",
    "opc.tcp://localhost:4840/simantha/"
)

TELEGRAF_CONF_PATH = os.environ.get(
    "TELEGRAF_CONF_PATH",
    str(_PROJECT_ROOT / "docker" / "telegraf" / "telegraf.conf")
)

sys.path.insert(0, str(_PROJECT_ROOT / "docker" / "telegraf"))

# ── Demo mode settings ──────────────────────────────────────────────────────
_SETTINGS_PATH = _SCRIPT_DIR / "demo_settings.json"
_SETTINGS_DEFAULTS = {"demo_mode": False, "retention_days": 30}


def _read_settings() -> dict:
    """Read demo_settings.json, returning defaults if missing or corrupt."""
    try:
        return {**_SETTINGS_DEFAULTS, **json.loads(_SETTINGS_PATH.read_text())}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_SETTINGS_DEFAULTS)


def _write_settings(data: dict) -> None:
    """Atomically write settings. Uses os.replace() — safe on Windows."""
    tmp = _SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, _SETTINGS_PATH)


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
            "warm_up_time": cfg.get("warm_up_time", 0),
        }
    return scenarios


# ---------------------------------------------------------------------------
# Recipe listing
# ---------------------------------------------------------------------------
def list_recipes():
    """List recipe YAML files from config/recipes/ directory.

    Returns a list of recipe names (without .yaml extension).
    """
    if not RECIPES_DIR.exists():
        return []
    return sorted(
        f.stem for f in RECIPES_DIR.glob("*.yaml")
        if f.is_file()
    )


def load_recipe(name):
    """Load a single recipe YAML file and return parsed content."""
    recipe_path = RECIPES_DIR / f"{name}.yaml"
    if not recipe_path.exists():
        return None
    with open(recipe_path, "r") as f:
        return _ryaml.load(f)


# ---------------------------------------------------------------------------
# Subprocess management
# ---------------------------------------------------------------------------
def _capture_logs():
    """Background thread: read subprocess stdout into ring buffer."""
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


def _regenerate_telegraf_config(scenario_name, run_id=""):
    """Regenerate telegraf.conf for the given scenario."""
    try:
        from generate_telegraf_conf import generate_telegraf_conf
        import yaml
        with open(CONFIG_PATH) as f:
            all_configs = yaml.safe_load(f)
        config = all_configs.get(scenario_name)
        if config and isinstance(config, dict):
            conf_text = generate_telegraf_conf(config, run_id=run_id)
            os.makedirs(os.path.dirname(os.path.abspath(TELEGRAF_CONF_PATH)),
                        exist_ok=True)
            with open(TELEGRAF_CONF_PATH, 'w') as f:
                f.write(conf_text)
            print(f"[WebUI] Regenerated Telegraf config for '{scenario_name}'"
                  f" ({conf_text.count('{name=')}"
                  f" nodes)")
    except Exception as e:
        print(f"[WebUI] Warning: Could not regenerate Telegraf config: {e}")


def start_simulation(scenario, seed=None, interarrival_time=None):
    """Spawn opcua_server.py as a subprocess."""
    global sim_process, sim_scenario, sim_recipe
    global sim_start_time, sim_run_id, sim_seed, sim_interarrival_time

    with sim_lock:
        stop_simulation()

        # Generate RunID for this run
        run_id = f"{scenario}_{dt.now().strftime('%Y%m%d_%H%M%S')}"
        sim_run_id = run_id

        _regenerate_telegraf_config(scenario, run_id=run_id)

        cmd = ["python", OPCUA_SERVER_SCRIPT, "--scenario", scenario]
        if seed is not None:
            cmd += ["--seed", str(seed)]
        if interarrival_time is not None:
            cmd += ["--interarrival-time", str(interarrival_time)]

        env = os.environ.copy()
        env["SIMANTHA_CONFIG_PATH"] = str(CONFIG_PATH)
        env["SIMANTHA_RUN_ID"] = run_id

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
        sim_recipe = None
        sim_start_time = time.time()
        sim_seed = seed
        sim_interarrival_time = interarrival_time

        # Disconnect OPC UA client (will reconnect lazily)
        _disconnect_opcua()

        # Background log capture thread
        t = threading.Thread(target=_capture_logs, daemon=True)
        t.start()


def start_simulation_recipe(recipe_name, seed=None, interarrival_time=None):
    """Spawn opcua_server.py in recipe mode as a subprocess."""
    global sim_process, sim_scenario, sim_recipe
    global sim_start_time, sim_run_id, sim_seed, sim_interarrival_time

    with sim_lock:
        stop_simulation()

        # Generate RunID for this run
        run_id = f"{recipe_name}_{dt.now().strftime('%Y%m%d_%H%M%S')}"
        sim_run_id = run_id

        # Load recipe to get base_scenario for Telegraf config
        recipe_data = load_recipe(recipe_name)
        if recipe_data and isinstance(recipe_data, dict):
            base_scenario = recipe_data.get("base_scenario", "balanced_line")
            _regenerate_telegraf_config(base_scenario, run_id=run_id)

        cmd = ["python", OPCUA_SERVER_SCRIPT, "--recipe", recipe_name]
        if seed is not None:
            cmd += ["--seed", str(seed)]
        if interarrival_time is not None:
            cmd += ["--interarrival-time", str(interarrival_time)]

        env = os.environ.copy()
        env["SIMANTHA_CONFIG_PATH"] = str(CONFIG_PATH)
        env["SIMANTHA_RUN_ID"] = run_id

        sim_log.clear()
        sim_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        sim_scenario = None
        sim_recipe = recipe_name
        sim_start_time = time.time()
        sim_seed = seed
        sim_interarrival_time = interarrival_time

        # Disconnect OPC UA client (will reconnect lazily)
        _disconnect_opcua()

        # Background log capture thread
        t = threading.Thread(target=_capture_logs, daemon=True)
        t.start()


def stop_simulation():
    """Gracefully stop the simulation subprocess."""
    global sim_process, sim_scenario, sim_recipe
    global sim_start_time, sim_run_id

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
    sim_recipe = None
    sim_start_time = None
    sim_run_id = None


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
    """Read key OPC UA variables for the web dashboard.

    Navigates the ISA-95 hierarchy:
      Enterprise > Site > Area > Line_Equipment > ...
    """
    client = _get_opcua_client()
    if client is None:
        return None
    try:
        root = client.get_objects_node()

        # Navigate ISA-95 hierarchy to line equipment node
        # Use multi-level get_child for efficiency
        line_equip = root.get_child([
            "2:WeylandIndustries", "2:LV426_Colony",
            "2:AtmosphereProcessor01", "2:Nostromo_BioProductPakaging_Equipment"
        ])

        # OperationsState
        ops_state = line_equip.get_child(["2:OperationsState"])
        sim_time = ops_state.get_child(["2:SimTime"]).get_value()

        controls = ops_state.get_child(["2:Controls"])
        interarrival = controls.get_child(["2:SetInterarrivalTime"]).get_value()

        # OperationsPerformance
        ops_perf = line_equip.get_child(["2:OperationsPerformance"])
        throughput = ops_perf.get_child(["2:Throughput"]).get_value()

        # Read machine states dynamically from Resources
        resources = line_equip.get_child(["2:Resources"])
        machines = {}
        machine_errors = []
        for i in range(1, 20):  # Up to 19 machines
            try:
                machine = resources.get_child([f"2:M{i}_Equipment"])
                ops_st = machine.get_child(["2:OperationsState"])
                state = ops_st.get_child(["2:State"]).get_value()

                ops_pf = machine.get_child(["2:OperationsPerformance"])
                partcount = ops_pf.get_child(["2:PartCount"]).get_value()
                target_ppm = ops_pf.get_child(["2:TargetPPM"]).get_value()
                actual_ppm = ops_pf.get_child(["2:ActualPPM"]).get_value()
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
            except Exception as e:
                if i <= 3:
                    machine_errors.append(f"M{i}_Equipment: {type(e).__name__}: {e}")
                break

        # Line-level OEE
        line_oee = {}
        try:
            oee_node = line_equip.get_child(["2:OEE"])
            line_oee["availability"] = oee_node.get_child(["2:Availability"]).get_value()
            line_oee["performance"] = oee_node.get_child(["2:Performance"]).get_value()
            line_oee["quality"] = oee_node.get_child(["2:Quality"]).get_value()
            line_oee["oee"] = oee_node.get_child(["2:OEE"]).get_value()
        except Exception:
            pass

        # Line-level KPIs from OperationsPerformance
        line_kpis = {}
        try:
            line_kpis["total_scrap"] = ops_perf.get_child(["2:TotalScrap"]).get_value()
            line_kpis["scrap_rate"] = ops_perf.get_child(["2:ScrapRate"]).get_value()
        except Exception:
            pass

        # Shift info (optional) — under SupportFunctions/ShiftManagement
        shift_info = {}
        try:
            shift_mgmt = line_equip.get_child(["2:SupportFunctions", "2:ShiftManagement"])
            shift_info["name"] = shift_mgmt.get_child(["2:CurrentShiftName"]).get_value()
            shift_info["elapsed"] = shift_mgmt.get_child(["2:ShiftElapsedTime"]).get_value()
            shift_info["duration"] = shift_mgmt.get_child(["2:ShiftDuration"]).get_value()
        except Exception:
            pass

        # Recipe state (optional) — under OperationsState/Recipe
        recipe_info = {}
        try:
            recipe_node = ops_state.get_child(["2:Recipe"])
            rname = recipe_node.get_child(["2:RecipeName"]).get_value()
            # Only include recipe info if a recipe is actually active
            if rname:
                recipe_info["recipe_name"] = rname
                recipe_info["segment_name"] = recipe_node.get_child(
                    ["2:SegmentName"]).get_value()
                recipe_info["segment_index"] = recipe_node.get_child(
                    ["2:SegmentIndex"]).get_value()
                recipe_info["total_segments"] = recipe_node.get_child(
                    ["2:TotalSegments"]).get_value()
                recipe_info["changeover_state"] = recipe_node.get_child(
                    ["2:ChangeoverState"]).get_value()
                recipe_info["segment_time_remaining"] = recipe_node.get_child(
                    ["2:SegmentTimeRemaining"]).get_value()
                recipe_info["segment_quantity_target"] = recipe_node.get_child(
                    ["2:SegmentQuantityTarget"]).get_value()
                recipe_info["segment_quantity_produced"] = recipe_node.get_child(
                    ["2:SegmentQuantityProduced"]).get_value()
        except Exception:
            pass

        result = {
            "sim_time": sim_time,
            "throughput": throughput,
            "interarrival_time": interarrival,
            "machines": machines,
            "line_oee": line_oee,
            "line_kpis": line_kpis,
            "shift": shift_info,
        }
        if recipe_info:
            result["recipe"] = recipe_info
        if machine_errors:
            result["machine_errors"] = machine_errors
        return result
    except Exception as e:
        import traceback
        print(f"[WebUI] OPC UA read error: {e}")
        traceback.print_exc()
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
        "recipe": sim_recipe,
        "run_id": sim_run_id,
        "uptime_seconds": uptime,
        "pid": sim_process.pid if sim_process else None,
        "seed": sim_seed,
        "interarrival_time": sim_interarrival_time,
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
    interarrival_time = data.get("interarrival_time")

    # Validate scenario exists
    scenarios = list_scenarios()
    if scenario not in scenarios:
        return jsonify({"error": f"Unknown scenario: {scenario}"}), 400

    if seed is not None:
        try:
            seed = int(seed)
        except (ValueError, TypeError):
            return jsonify({"error": "seed must be an integer"}), 400

    if interarrival_time is not None:
        try:
            interarrival_time = float(interarrival_time)
            if interarrival_time <= 0:
                return jsonify({"error": "interarrival_time must be positive"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "interarrival_time must be a number"}), 400

    start_simulation(scenario, seed, interarrival_time)
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
    """Runtime control endpoint.

    SetInterarrivalTime and CmdPauseLine have been removed — interarrival is
    a start-time parameter and pause is handled via /api/stop.  This endpoint
    is kept for backward compatibility but no longer writes OPC UA variables.
    """
    return jsonify({"status": "ok", "written": {}})


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
# Recipe API routes
# ---------------------------------------------------------------------------
@app.route("/api/recipes")
def api_recipes():
    """List available recipe names from config/recipes/."""
    return jsonify(list_recipes())


@app.route("/api/recipe/<name>")
def api_get_recipe(name):
    """Return full config for a single recipe as JSON."""
    data = load_recipe(name)
    if data is None:
        return jsonify({"error": f"Recipe '{name}' not found"}), 404
    return jsonify(data)


@app.route("/api/recipe", methods=["POST"])
def api_create_recipe():
    """Create a new recipe YAML file.

    Accepts JSON body with 'name' (string) and 'content' (YAML string).
    """
    data = request.get_json(force=True)
    name = data.get("name")
    content = data.get("content")

    if not name:
        return jsonify({"error": "Missing 'name' field"}), 400
    if not content:
        return jsonify({"error": "Missing 'content' field"}), 400

    # Sanitize name: only allow alphanumeric, underscore, hyphen
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return jsonify({"error": "Invalid recipe name. "
                        "Use only letters, numbers, underscores, hyphens."}), 400

    # Ensure recipes directory exists
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)

    recipe_path = RECIPES_DIR / f"{name}.yaml"
    if recipe_path.exists():
        return jsonify({"error": f"Recipe '{name}' already exists"}), 409

    # Validate that content is valid YAML
    try:
        _ryaml.load(StringIO(content))
    except Exception as e:
        return jsonify({"error": f"Invalid YAML: {e}"}), 400

    with open(recipe_path, "w") as f:
        f.write(content)

    return jsonify({"status": "created", "recipe": name}), 201


@app.route("/api/recipe/<name>", methods=["PUT"])
def api_update_recipe(name):
    """Update an existing recipe YAML file.

    Accepts JSON body with 'content' (YAML string).
    """
    recipe_path = RECIPES_DIR / f"{name}.yaml"
    if not recipe_path.exists():
        return jsonify({"error": f"Recipe '{name}' not found"}), 404

    data = request.get_json(force=True)
    content = data.get("content")

    if not content:
        return jsonify({"error": "Missing 'content' field"}), 400

    # Validate that content is valid YAML
    try:
        _ryaml.load(StringIO(content))
    except Exception as e:
        return jsonify({"error": f"Invalid YAML: {e}"}), 400

    with open(recipe_path, "w") as f:
        f.write(content)

    return jsonify({"status": "ok", "recipe": name})


@app.route("/recipes")
def recipes_editor():
    """Render the recipe editor page."""
    return render_template("recipes.html")


@app.route("/api/recipe/<name>/yaml")
def api_recipe_yaml(name):
    """Return raw YAML text for a recipe."""
    recipe_path = RECIPES_DIR / f"{name}.yaml"
    if not recipe_path.exists():
        return jsonify({"error": f"Recipe '{name}' not found"}), 404
    with open(recipe_path, "r") as f:
        content = f.read()
    return jsonify({"yaml": content})


@app.route("/api/recipe/<name>", methods=["DELETE"])
def api_delete_recipe(name):
    """Delete a recipe YAML file."""
    recipe_path = RECIPES_DIR / f"{name}.yaml"
    if not recipe_path.exists():
        return jsonify({"error": f"Recipe '{name}' not found"}), 404

    # Sanitize: ensure the name doesn't escape the recipes directory
    try:
        recipe_path.resolve().relative_to(RECIPES_DIR.resolve())
    except ValueError:
        return jsonify({"error": "Invalid recipe name"}), 400

    recipe_path.unlink()
    return jsonify({"status": "deleted", "recipe": name})


@app.route("/api/start-recipe", methods=["POST"])
def api_start_recipe():
    """Start simulation with a recipe.

    Accepts JSON body with 'recipe' (name) and optional 'seed' (integer).
    Spawns opcua_server.py with --recipe flag.
    """
    data = request.get_json(force=True) if request.data else {}
    recipe_name = data.get("recipe")
    seed = data.get("seed")
    interarrival_time = data.get("interarrival_time")

    if not recipe_name:
        return jsonify({"error": "Missing 'recipe' field"}), 400

    # Validate recipe exists
    recipe_path = RECIPES_DIR / f"{recipe_name}.yaml"
    if not recipe_path.exists():
        return jsonify({"error": f"Unknown recipe: {recipe_name}"}), 400

    if seed is not None:
        try:
            seed = int(seed)
        except (ValueError, TypeError):
            return jsonify({"error": "seed must be an integer"}), 400

    if interarrival_time is not None:
        try:
            interarrival_time = float(interarrival_time)
            if interarrival_time <= 0:
                return jsonify({"error": "interarrival_time must be positive"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "interarrival_time must be a number"}), 400

    start_simulation_recipe(recipe_name, seed, interarrival_time)
    return jsonify({"status": "started", "recipe": recipe_name, "seed": seed})


# ---------------------------------------------------------------------------
# Historian CSV download routes
# ---------------------------------------------------------------------------
@app.route("/api/historian/files")
def list_historian_files():
    """List available historian CSV files with metadata."""
    hist_dir = _PROJECT_ROOT / "results" / "historian"
    if not hist_dir.exists():
        return jsonify({"files": []})
    files = sorted(hist_dir.glob("*_events*.csv"), key=os.path.getmtime, reverse=True)
    return jsonify({"files": [
        {
            "name": f.name,
            "size_mb": round(f.stat().st_size / 1048576, 1),
            "modified": dt.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in files
    ]})


def _merge_csv_files(file_paths):
    """Merge multiple CSV rotation files into a single in-memory CSV string.

    Keeps the header from the first file only, concatenates data rows from all
    files in order. Returns (csv_string, download_filename).
    """
    buf = StringIO()
    header_written = False
    for path in file_paths:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i == 0:
                    if not header_written:
                        buf.write(line)
                        header_written = True
                else:
                    buf.write(line)
    # Use the base filename (no rotation suffix) as download name
    base = file_paths[0]
    stem = base.stem
    run_id = stem.rsplit("_events", 1)[0] if "_events" in stem else stem
    download_name = f"{run_id}_events_merged.csv"
    return buf.getvalue(), download_name


def _get_run_files(filename, hist_dir):
    """Return sorted rotation files for the run_id implied by *filename*."""
    stem = Path(filename).stem
    run_id = stem.rsplit("_events", 1)[0] if "_events" in stem else stem
    import re as _re
    def _sort_key(p):
        m = _re.search(r"_events_(\d+)$", p.stem)
        return int(m.group(1)) if m else -1
    files = sorted(hist_dir.glob(f"{run_id}_events*.csv"), key=_sort_key)
    return files if files else []


@app.route("/api/historian/download/<filename>")
def download_historian_file(filename):
    """Serve historian CSV(s) for the given run as an attachment.

    If the run has multiple rotation files they are merged into one download.
    """
    hist_dir = _PROJECT_ROOT / "results" / "historian"
    if ".." in filename or not filename.endswith(".csv"):
        return jsonify({"error": "Invalid filename"}), 400
    if not (hist_dir / filename).exists():
        return jsonify({"error": "File not found"}), 404
    run_files = _get_run_files(filename, hist_dir)
    if len(run_files) <= 1:
        return send_from_directory(str(hist_dir), filename, as_attachment=True)
    csv_data, download_name = _merge_csv_files(run_files)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={download_name}"},
    )


@app.route("/api/historian/download")
def download_latest_historian():
    """Download the most recent historian run as a single merged CSV."""
    hist_dir = _PROJECT_ROOT / "results" / "historian"
    if not hist_dir.exists():
        return jsonify({"error": "No historian files found"}), 404
    files = sorted(hist_dir.glob("*_events*.csv"), key=os.path.getmtime)
    if not files:
        return jsonify({"error": "No historian files found"}), 404
    # Use the most recent file to identify the run, then merge all its parts
    run_files = _get_run_files(files[-1].name, hist_dir)
    if len(run_files) <= 1:
        return send_from_directory(str(hist_dir), files[-1].name, as_attachment=True)
    csv_data, download_name = _merge_csv_files(run_files)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={download_name}"},
    )


# ---------------------------------------------------------------------------
# Report engine (lazy import — pandas may not be installed in all envs)
# ---------------------------------------------------------------------------
_report_cache = {}  # {(filename, mtime): {"analysis": dict, "expires": float}}
_REPORT_CACHE_TTL = 60  # seconds


def _get_report_engine():
    """Lazy-import report_engine to avoid hard pandas dependency at startup."""
    try:
        import report_engine
        return report_engine
    except ImportError as e:
        print(f"[WebUI] report_engine import failed: {e}")
        return None


def _get_historian_dir():
    """Return the historian results directory."""
    return _PROJECT_ROOT / "results" / "historian"


def _analyze_csv(filename):
    """Load and analyze a historian CSV file, with caching."""
    hist_dir = _get_historian_dir()
    filepath = hist_dir / filename
    if not filepath.exists():
        return None, "File not found"

    re_mod = _get_report_engine()
    if re_mod is None:
        return None, "pandas is required for reports. Install with: pip install pandas"

    mtime = filepath.stat().st_mtime
    cache_key = (filename, mtime)
    now = time.time()

    # Check cache
    if cache_key in _report_cache:
        cached = _report_cache[cache_key]
        if cached["expires"] > now:
            return cached["analysis"], None

    # Parse and analyze
    try:
        df = re_mod.load_historian_csv(str(filepath))
        analysis = re_mod.run_full_analysis(df)
        # Auto-append to run index
        re_mod.append_run_index(str(filepath), analysis)
    except Exception as e:
        return None, f"Analysis failed: {e}"

    # Cache result
    _report_cache[cache_key] = {
        "analysis": analysis,
        "expires": now + _REPORT_CACHE_TTL,
    }

    return analysis, None


# ---------------------------------------------------------------------------
# Report routes
# ---------------------------------------------------------------------------
@app.route("/runs")
def runs_page():
    """Run history page."""
    return render_template("runs.html")


@app.route("/api/runs")
def api_runs():
    """Merged run listing: run_index.json + CSV files + current live run.

    Returns {"runs": [...], "current_run_id": "..."} sorted newest first.
    """
    import json as _json
    hist_dir = _get_historian_dir()
    runs_by_id = {}  # run_id -> entry dict

    # 1. Load run_index.json entries (analyzed runs)
    index_path = hist_dir / "run_index.json"
    if index_path.exists():
        try:
            with open(index_path) as f:
                for entry in _json.load(f):
                    rid = entry.get("run_id", "")
                    if rid:
                        entry["analyzed"] = True
                        runs_by_id[rid] = entry
        except (ValueError, IOError):
            pass

    # 2. List CSV historian files, extract run_id from filename
    if hist_dir.exists():
        for csv_file in hist_dir.glob("*_events*.csv"):
            name = csv_file.stem
            # Pattern: {run_id}_events.csv or {run_id}_events_suffix.csv
            run_id = name.rsplit("_events", 1)[0] if "_events" in name else name
            if run_id not in runs_by_id:
                # Extract scenario from run_id
                scenario = run_id
                import re as _re
                date_match = _re.search(r'_\d{8}_\d{6}$', run_id)
                if date_match:
                    scenario = run_id[:date_match.start()]
                runs_by_id[run_id] = {
                    "run_id": run_id,
                    "scenario": scenario,
                    "csv_file": csv_file.name,
                    "analyzed": False,
                }
            elif "csv_file" not in runs_by_id[run_id]:
                runs_by_id[run_id]["csv_file"] = csv_file.name

    # 3. Include current live run
    current_run_id = sim_run_id
    if current_run_id and current_run_id not in runs_by_id:
        scenario = sim_scenario or sim_recipe or ""
        runs_by_id[current_run_id] = {
            "run_id": current_run_id,
            "scenario": scenario,
            "analyzed": False,
            "status": "running",
        }
    elif current_run_id and current_run_id in runs_by_id:
        running = sim_process is not None and sim_process.poll() is None
        if running:
            runs_by_id[current_run_id]["status"] = "running"

    # 4. Sort by date descending (parse YYYYMMDD_HHMMSS from run_id)
    def _sort_key(entry):
        import re as _re
        m = _re.search(r'(\d{8}_\d{6})', entry.get("run_id", ""))
        return m.group(1) if m else "00000000_000000"

    runs_list = sorted(runs_by_id.values(), key=_sort_key, reverse=True)

    return jsonify({
        "runs": runs_list,
        "current_run_id": current_run_id,
    })


@app.route("/api/runs", methods=["DELETE"])
def api_delete_runs():
    """Delete runs from run_index.json and optionally CSV files."""
    import json as _json
    data = request.get_json(force=True)
    run_ids = data.get("run_ids", [])
    delete_csv = data.get("delete_csv", False)

    if not run_ids:
        return jsonify({"error": "No run_ids provided"}), 400

    hist_dir = _get_historian_dir()

    # 1. Remove from run_index.json
    index_path = hist_dir / "run_index.json"
    if index_path.exists():
        try:
            with open(index_path) as f:
                index = _json.load(f)
            original_len = len(index)
            index = [e for e in index if e.get("run_id") not in run_ids]
            with open(index_path, "w") as f:
                _json.dump(index, f, indent=2)
        except (ValueError, IOError):
            pass

    # 2. Optionally delete CSV files
    deleted_csvs = []
    if delete_csv and hist_dir.exists():
        for rid in run_ids:
            for csv_file in hist_dir.glob(f"{rid}_events*.csv"):
                csv_file.unlink()
                deleted_csvs.append(csv_file.name)

    return jsonify({"deleted": run_ids, "deleted_csvs": deleted_csvs})


@app.route("/reports")
def reports_page():
    """Production run analysis page with charts."""
    return render_template("reports.html")


@app.route("/validation")
def validation_page():
    """Pipeline validation page."""
    return render_template("validation.html")


@app.route("/docs")
def docs_page():
    """Documentation page."""
    return render_template("docs.html")


@app.route("/api/reports/files")
def api_report_files():
    """List historian CSV files available for analysis."""
    hist_dir = _get_historian_dir()
    if not hist_dir.exists():
        return jsonify({"files": []})
    files = sorted(hist_dir.glob("*_events*.csv"), key=os.path.getmtime, reverse=True)
    result = []
    for f in files:
        # Try to extract scenario name from filename
        name = f.stem
        scenario = name.rsplit("_events", 1)[0] if "_events" in name else name
        import re as _re
        date_match = _re.search(r'_(\d{8}_\d{6})$', scenario)
        if date_match:
            scenario = scenario[:date_match.start()]
        result.append({
            "name": f.name,
            "scenario": scenario,
            "size_mb": round(f.stat().st_size / 1048576, 2),
            "modified": dt.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return jsonify({"files": result})


@app.route("/api/reports/analyze", methods=["POST"])
def api_report_analyze():
    """Run full analysis on a historian CSV file."""
    data = request.get_json(force=True) if request.data else {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Missing 'filename' field"}), 400
    if ".." in filename or not filename.endswith(".csv"):
        return jsonify({"error": "Invalid filename"}), 400

    analysis, error = _analyze_csv(filename)
    if error:
        return jsonify({"error": error}), 400 if "not found" in error.lower() else 500

    return jsonify(analysis)


@app.route("/api/reports/runs")
def api_report_runs():
    """Return the run index for multi-run comparison."""
    index_path = _get_historian_dir() / "run_index.json"
    if not index_path.exists():
        return jsonify({"runs": []})
    try:
        import json as _json
        with open(index_path) as f:
            runs = _json.load(f)
        return jsonify({"runs": runs})
    except Exception:
        return jsonify({"runs": []})


@app.route("/api/validation/run", methods=["POST"])
def api_validation_run():
    """Run CSV vs InfluxDB pipeline validation."""
    data = request.get_json(force=True) if request.data else {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Missing 'filename' field"}), 400
    if ".." in filename or not filename.endswith(".csv"):
        return jsonify({"error": "Invalid filename"}), 400

    re_mod = _get_report_engine()
    if re_mod is None:
        return jsonify({"error": "pandas is required"}), 500

    hist_dir = _get_historian_dir()
    filepath = hist_dir / filename
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    # Get InfluxDB connection details from env
    influx_url = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
    influx_token = os.environ.get("INFLUXDB_TOKEN", "simantha-dev-token")
    influx_org = os.environ.get("INFLUXDB_ORG", "simantha")
    influx_bucket = os.environ.get("INFLUXDB_BUCKET", "manufacturing")

    try:
        # Import the CLI query function (it has the InfluxDB logic)
        sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
        from analyze_historian import query_influxdb_telegraf

        df = re_mod.load_merged_historian_csv(str(filepath))

        # Extract run_id and time range from CSV for scoped queries
        csv_run_id = None
        time_start = None
        time_end = None
        if "run_id" in df.columns and len(df) > 0:
            import pandas as pd
            first_rid = df["run_id"].iloc[0]
            if pd.notna(first_rid) and str(first_rid).strip():
                csv_run_id = str(first_rid).strip()
        if "wall_clock" in df.columns and len(df) > 0:
            time_start = str(df["wall_clock"].iloc[0])
            time_end = str(df["wall_clock"].iloc[-1])

        influx_data = query_influxdb_telegraf(
            influx_url, influx_token, influx_org, influx_bucket,
            run_id=csv_run_id, time_start=time_start, time_end=time_end,
        )

        validation = re_mod.validate_pipeline(df, influx_data)
        return jsonify(validation)
    except ImportError:
        return jsonify({"error": "influxdb-client package is required"}), 500
    except Exception as e:
        return jsonify({"error": f"Validation failed: {e}"}), 500


@app.route("/api/validation/influxdb/status")
def api_influxdb_status():
    """Check InfluxDB connectivity."""
    influx_url = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
    try:
        from influxdb_client import InfluxDBClient
        influx_token = os.environ.get("INFLUXDB_TOKEN", "simantha-dev-token")
        influx_org = os.environ.get("INFLUXDB_ORG", "simantha")
        client = InfluxDBClient(url=influx_url, token=influx_token, org=influx_org)
        health = client.health()
        client.close()
        return jsonify({
            "connected": health.status == "pass",
            "url": influx_url,
            "status": health.status,
            "message": health.message,
        })
    except ImportError:
        return jsonify({"connected": False, "url": influx_url, "error": "influxdb-client not installed"})
    except Exception as e:
        return jsonify({"connected": False, "url": influx_url, "error": str(e)})


# ---------------------------------------------------------------------------
# Neo4j graph helpers
# ---------------------------------------------------------------------------

def _get_neo4j_driver():
    """Return a Neo4j driver using env vars. Returns None if not configured."""
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not uri or not password:
        return None
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=3)
        return driver
    except Exception:
        return None


_STATE_COLOURS = {
    "PROCESSING":   "#2ecc71",
    "IDLE":         "#95a5a6",
    "STARVED":      "#e67e22",
    "BLOCKED":      "#f39c12",
    "FAILED":       "#e74c3c",
    "UNDER_REPAIR": "#9b59b6",
    "DEGRADED":     "#d4ac0d",
}


def _query_neo4j_causal(run_id: str) -> dict:
    driver = _get_neo4j_driver()
    if not driver:
        raise RuntimeError("Neo4j not configured")
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (src)-[:HAD_EVENT]->(start:Event {run_id: $run_id, new_state: 'UNDER_REPAIR'})
                WITH start ORDER BY start.sim_time DESC LIMIT 1
                MATCH path = (start)-[:CAUSED*1..8]->(end:Event)
                UNWIND relationships(path) AS rel
                WITH startNode(rel) AS n1, endNode(rel) AS n2, rel
                MATCH (eq1)-[:HAD_EVENT]->(n1)
                MATCH (eq2)-[:HAD_EVENT]->(n2)
                RETURN DISTINCT
                  elementId(n1) AS from_id, eq1.name AS from_name, n1.new_state AS from_state,
                  elementId(n2) AS to_id,   eq2.name AS to_name,   n2.new_state AS to_state,
                  rel.type AS cause_type,   rel.lag_s AS lag_s
                LIMIT 100
                """,
                run_id=run_id,
            )
            nodes, edges, seen_nodes = [], [], set()
            for row in result:
                for nid, nname, nstate in [
                    (row["from_id"], row["from_name"], row["from_state"]),
                    (row["to_id"],   row["to_name"],   row["to_state"]),
                ]:
                    if nid not in seen_nodes:
                        seen_nodes.add(nid)
                        nodes.append({
                            "id": nid, "label": f"{nname}\n{nstate or ''}",
                            "color": _STATE_COLOURS.get(nstate, "#7f8c8d"),
                        })
                edges.append({
                    "from": row["from_id"], "to": row["to_id"],
                    "label": f"{row['cause_type']} ({row['lag_s']}s)",
                    "arrows": "to",
                })
        return {"nodes": nodes, "edges": edges}
    finally:
        driver.close()


def _query_neo4j_topology(run_id: str) -> dict:
    driver = _get_neo4j_driver()
    if not driver:
        raise RuntimeError("Neo4j not configured")
    try:
        with driver.session() as session:
            eq_result = session.run(
                """
                MATCH (eq {run_id: $run_id})-[:HAD_EVENT]->(e:Event)
                WHERE eq:Machine OR eq:Buffer
                WITH eq, e ORDER BY e.sim_time DESC
                WITH eq, collect(e)[0] AS latest
                RETURN eq.name AS name, labels(eq)[0] AS type,
                       latest.new_state AS state
                """,
                run_id=run_id,
            )
            nodes, seen = [], set()
            for row in eq_result:
                if row["name"] not in seen:
                    seen.add(row["name"])
                    nodes.append({
                        "id": row["name"], "label": row["name"],
                        "color": _STATE_COLOURS.get(row["state"], "#95a5a6"),
                        "shape": "box" if row["type"] == "Buffer" else "ellipse",
                    })
            feeds_result = session.run(
                """
                MATCH (a {run_id: $run_id})-[:FEEDS]->(b {run_id: $run_id})
                WHERE (a:Machine OR a:Buffer) AND (b:Machine OR b:Buffer)
                RETURN a.name AS from_name, b.name AS to_name
                """,
                run_id=run_id,
            )
            edges = [{"from": r["from_name"], "to": r["to_name"], "arrows": "to"} for r in feeds_result]
        return {"nodes": nodes, "edges": edges}
    finally:
        driver.close()


def _query_neo4j_compare(run_a: str, run_b: str) -> dict:
    driver = _get_neo4j_driver()
    if not driver:
        raise RuntimeError("Neo4j not configured")
    stats = {}
    try:
        with driver.session() as session:
            for run_id, key in [(run_a, "run_a"), (run_b, "run_b")]:
                result = session.run(
                    """
                    MATCH (r:Run {run_id: $run_id})
                    OPTIONAL MATCH (r)-[:INCLUDES]->(m:Machine)-[:HAD_EVENT]->(e:Event)-[:CAUSED*]->(e2:Event)
                    WITH r, count(DISTINCT e) AS caused_count
                    OPTIONAL MATCH path = (e1:Event {run_id: $run_id})-[:CAUSED*]->(e2:Event)
                    WITH caused_count, max(length(path)) AS max_depth
                    OPTIONAL MATCH (m:Machine {run_id: $run_id})-[:HAD_EVENT]->(e:Event {new_state: 'UNDER_REPAIR'})
                    WITH caused_count, max_depth, count(e) AS repair_count, m.name AS mname
                    ORDER BY repair_count DESC LIMIT 1
                    RETURN caused_count, max_depth, repair_count, mname AS top_node
                    """,
                    run_id=run_id,
                )
                row = result.single()
                stats[key] = {
                    "run_id":       run_id,
                    "total_caused": row["caused_count"] or 0,
                    "max_depth":    row["max_depth"] or 0,
                    "repair_count": row["repair_count"] or 0,
                    "top_node":     row["top_node"] or "—",
                } if row else {"run_id": run_id, "total_caused": 0, "max_depth": 0, "repair_count": 0, "top_node": "—"}
        return stats
    finally:
        driver.close()


def _query_neo4j_node_events(run_id: str, node_name: str) -> list:
    driver = _get_neo4j_driver()
    if not driver:
        raise RuntimeError("Neo4j not configured")
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (eq {name: $node_name, run_id: $run_id})-[:HAD_EVENT]->(e:Event)
                RETURN e.sim_time AS sim_time, e.type AS type, e.new_state AS new_state,
                       e.old_state AS old_state, e.oee AS oee
                ORDER BY e.sim_time DESC LIMIT 5
                """,
                run_id=run_id, node_name=node_name,
            )
            rows = [dict(r) for r in result]
        return rows
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# Graph tab routes
# ---------------------------------------------------------------------------

@app.route("/graph")
def graph_page():
    return render_template("graph.html")


@app.route("/api/graph/causal")
def api_graph_causal():
    run_id = request.args.get("run_id", "").strip()
    if not run_id:
        return jsonify({"error": "run_id required"}), 400
    try:
        return jsonify(_query_neo4j_causal(run_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.route("/api/graph/topology")
def api_graph_topology():
    run_id = request.args.get("run_id", "").strip()
    if not run_id:
        return jsonify({"error": "run_id required"}), 400
    try:
        return jsonify(_query_neo4j_topology(run_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.route("/api/graph/compare")
def api_graph_compare():
    run_a = request.args.get("run_a", "").strip()
    run_b = request.args.get("run_b", "").strip()
    if not run_a or not run_b:
        return jsonify({"error": "run_a and run_b required"}), 400
    try:
        return jsonify(_query_neo4j_compare(run_a, run_b))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.route("/api/graph/node_events")
def api_graph_node_events():
    run_id = request.args.get("run_id", "").strip()
    node_name = request.args.get("node", "").strip()
    if not run_id or not node_name:
        return jsonify({"error": "run_id and node required"}), 400
    try:
        return jsonify(_query_neo4j_node_events(run_id, node_name))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(_read_settings())


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    body = request.get_json(force=True) or {}
    demo_mode = bool(body.get("demo_mode", False))
    retention_days = body.get("retention_days", 30)
    if not isinstance(retention_days, int) or not (7 <= retention_days <= 365):
        return jsonify({"error": "retention_days must be an integer between 7 and 365"}), 400
    settings = {"demo_mode": demo_mode, "retention_days": int(retention_days)}
    _write_settings(settings)
    return jsonify(settings)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("WEBUI_PORT", 8080))
    print(f"[WebUI] Starting on port {port}")
    print(f"[WebUI] Config: {CONFIG_PATH}")
    app.jinja_env.auto_reload = True
    app.run(host="0.0.0.0", port=port, debug=False)
