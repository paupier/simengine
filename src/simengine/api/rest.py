"""Embedded REST API (build plan P6.4, endpoints per clone_target_architecture §4).

A thin transport over logic that already exists: all mutating config endpoints
reuse the config_loader / recipe_runner validators, and GET /api/v1/state
returns the exact snapshot object the publishers consume (dataclasses.asdict).
Scenario/recipe writes go through ruamel round-trip loading so YAML comments
are preserved.
"""
import io
from dataclasses import asdict

from flask import Blueprint, Flask, jsonify, render_template, request
from ruamel.yaml import YAML

from simengine.config.loader import (
    get_config_path,
    get_recipes_dir,
    validate_comms,
    validate_serial_topology,
)
from simengine.runtime.recipe_runner import parse_recipe, validate_recipe
from simengine.runtime.run_manager import IDLE, RunConflictError, RunManager

_yaml = YAML()
_yaml.preserve_quotes = True


def _load_scenarios_file():
    path = get_config_path()
    with open(path) as f:
        return _yaml.load(f) or {}, path


def _dump_scenarios_file(data, path):
    with open(path, "w") as f:
        _yaml.dump(data, f)


def _plain(obj):
    """ruamel round-trip objects -> plain dict/list for validation + JSON."""
    buf = io.StringIO()
    _yaml.dump(obj, buf)
    import yaml as pyyaml
    return pyyaml.safe_load(buf.getvalue())


def create_api_blueprint(run_manager: RunManager) -> Blueprint:
    api = Blueprint("api", __name__)

    # ----- state -----

    @api.get("/api/v1/state")
    def get_state():
        snap = run_manager.latest_snapshot
        if snap is None:
            return jsonify({"error": "no run"}), 404
        return jsonify(asdict(snap))

    @api.get("/api/v1/state/stations/<name>")
    def get_station(name):
        snap = run_manager.latest_snapshot
        if snap is None:
            return jsonify({"error": "no run"}), 404
        st = snap.stations.get(name)
        if st is None:
            return jsonify({"error": f"unknown station '{name}'"}), 404
        return jsonify(asdict(st))

    # ----- runs -----

    @api.get("/api/v1/runs/current")
    def get_current_run():
        return jsonify(run_manager.status())

    @api.post("/api/v1/runs")
    def start_run():
        body = request.get_json(force=True, silent=True) or {}
        scenario = body.get("scenario")
        if not scenario:
            return jsonify({"error": "scenario required"}), 400
        try:
            run_id = run_manager.start(
                scenario,
                seed=body.get("seed"),
                speed_ratio=float(body.get("speed_ratio", 1.0)),
            )
        except RunConflictError as exc:
            return jsonify({"error": str(exc)}), 409
        except (ValueError, FileNotFoundError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"run_id": run_id}), 201

    @api.post("/api/v1/runs/recipe")
    def start_recipe():
        body = request.get_json(force=True, silent=True) or {}
        recipe = body.get("recipe")
        if not recipe:
            return jsonify({"error": "recipe required"}), 400
        try:
            run_id = run_manager.start_recipe(
                recipe, seed=body.get("seed"),
                speed_ratio=float(body.get("speed_ratio", 1.0)),
            )
        except RunConflictError as exc:
            return jsonify({"error": str(exc)}), 409
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"run_id": run_id}), 201

    @api.delete("/api/v1/runs/current")
    def stop_run():
        if run_manager.state == IDLE:
            return jsonify({"error": "no active run"}), 409
        run_manager.stop()
        return jsonify({"stopped": True})

    # ----- scenarios -----

    @api.get("/api/v1/scenarios")
    def list_scenarios():
        data, _ = _load_scenarios_file()
        return jsonify(sorted(data.keys()))

    @api.get("/api/v1/scenarios/<name>")
    def get_scenario(name):
        data, _ = _load_scenarios_file()
        if name not in data:
            return jsonify({"error": f"unknown scenario '{name}'"}), 404
        return jsonify(_plain(data[name]))

    @api.put("/api/v1/scenarios/<name>")
    def put_scenario(name):
        body = request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "scenario body must be a JSON object"}), 400
        try:
            validate_serial_topology(body)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        data, path = _load_scenarios_file()
        if name not in data:
            return jsonify({"error": f"unknown scenario '{name}'"}), 404
        data[name] = body
        _dump_scenarios_file(data, path)
        return jsonify({"updated": name})

    @api.post("/api/v1/scenarios")
    def post_scenario():
        body = request.get_json(force=True, silent=True) or {}
        name = body.get("name")
        config = body.get("config")
        if not name or not isinstance(config, dict):
            return jsonify({"error": "body must be {name, config}"}), 400
        try:
            validate_serial_topology(config)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        data, path = _load_scenarios_file()
        if name in data:
            return jsonify({"error": f"scenario '{name}' already exists"}), 409
        data[name] = config
        _dump_scenarios_file(data, path)
        return jsonify({"created": name}), 201

    # ----- recipes -----

    @api.get("/api/v1/recipes")
    def list_recipes():
        recipes_dir = get_recipes_dir()
        names = sorted(p.stem for p in recipes_dir.glob("*.yaml"))
        return jsonify(names)

    @api.get("/api/v1/recipes/<name>")
    def get_recipe(name):
        path = get_recipes_dir() / f"{name}.yaml"
        if not path.exists():
            return jsonify({"error": f"unknown recipe '{name}'"}), 404
        with open(path) as f:
            return jsonify(_plain(_yaml.load(f)))

    @api.put("/api/v1/recipes/<name>")
    def put_recipe(name):
        body = request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "recipe body must be a JSON object"}), 400
        try:
            recipe = parse_recipe(body)
            validate_recipe(recipe)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        path = get_recipes_dir() / f"{name}.yaml"
        if not path.exists():
            return jsonify({"error": f"unknown recipe '{name}'"}), 404
        with open(path, "w") as f:
            _yaml.dump(body, f)
        return jsonify({"updated": name})

    @api.post("/api/v1/recipes")
    def post_recipe():
        body = request.get_json(force=True, silent=True) or {}
        name = body.get("name")
        config = body.get("config")
        if not name or not isinstance(config, dict):
            return jsonify({"error": "body must be {name, config}"}), 400
        try:
            recipe = parse_recipe(config)
            validate_recipe(recipe)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        path = get_recipes_dir() / f"{name}.yaml"
        if path.exists():
            return jsonify({"error": f"recipe '{name}' already exists"}), 409
        with open(path, "w") as f:
            _yaml.dump(config, f)
        return jsonify({"created": name}), 201

    # ----- comms -----

    @api.get("/api/v1/comms")
    def get_comms():
        scenario = request.args.get("scenario")
        if not scenario:
            return jsonify({"error": "scenario query parameter required"}), 400
        data, _ = _load_scenarios_file()
        if scenario not in data:
            return jsonify({"error": f"unknown scenario '{scenario}'"}), 404
        return jsonify(_plain(data[scenario]).get("comms", {}))

    @api.put("/api/v1/comms")
    def put_comms():
        body = request.get_json(force=True, silent=True) or {}
        scenario = body.get("scenario")
        comms = body.get("comms")
        if not scenario or not isinstance(comms, dict):
            return jsonify({"error": "body must be {scenario, comms}"}), 400
        try:
            validate_comms({"comms": comms})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        data, path = _load_scenarios_file()
        if scenario not in data:
            return jsonify({"error": f"unknown scenario '{scenario}'"}), 404
        data[scenario]["comms"] = comms
        _dump_scenarios_file(data, path)
        return jsonify({"updated": scenario, "applies": "next_run"})

    # ----- plugins helper (comms page) -----

    @api.get("/api/v1/plugins")
    def list_plugins():
        import importlib.util
        known = {
            "sparkplug": "mqtt_spb_wrapper",
            "historian-csv": "simengine_historian_csv",
            "historian-influx": "influxdb_client",
            "historian-neo4j": "neo4j",
            "analysis": "pandas",
        }
        return jsonify({
            name: importlib.util.find_spec(module) is not None
            for name, module in known.items()
        })

    # ----- liveness -----

    @api.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "run_state": run_manager.state})

    return api


def create_app(run_manager: RunManager) -> Flask:
    """Flask app: REST blueprint + 3-page UI."""
    app = Flask(__name__, template_folder="ui")
    app.register_blueprint(create_api_blueprint(run_manager))

    @app.get("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/configure")
    def configure():
        return render_template("configure.html")

    @app.get("/comms")
    def comms():
        return render_template("comms.html")

    return app
