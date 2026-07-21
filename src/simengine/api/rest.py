"""Embedded REST API (build plan P6.4, endpoints per clone_target_architecture §4).

A thin transport over logic that already exists: all mutating config endpoints
reuse the config_loader / recipe_runner validators, and GET /api/v1/state
returns the exact snapshot object the publishers consume (dataclasses.asdict).
Scenario/recipe writes go through ruamel round-trip loading so YAML comments
are preserved.
"""
from dataclasses import asdict

from flask import Blueprint, Flask, jsonify, render_template, request

from simengine.api.config_files import (
    dump_recipe_file,
    recipe_path,
    dump_scenarios_file as _dump_scenarios_file,
    load_recipe_file,
    load_scenarios_file as _load_scenarios_file,
    plain as _plain,
)
from simengine.config.loader import (
    get_recipes_dir,
    validate_comms,
    validate_serial_topology,
)
from simengine.engine.knowledge_graph import build_knowledge_graph
from simengine.runtime.recipe_runner import parse_recipe, validate_recipe
from simengine.runtime.run_manager import IDLE, RunConflictError, RunManager


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

    @api.post("/api/v1/scenarios/validate")
    def validate_scenario_draft():
        body = request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return jsonify({"valid": False, "error": "body must be a JSON object"}), 400
        try:
            validate_serial_topology(body)
        except ValueError as exc:
            return jsonify({"valid": False, "error": str(exc)}), 400
        return jsonify({"valid": True})

    # ----- recipes -----

    @api.get("/api/v1/recipes")
    def list_recipes():
        recipes_dir = get_recipes_dir()
        names = sorted(p.stem for p in recipes_dir.glob("*.yaml"))
        return jsonify(names)

    @api.get("/api/v1/recipes/<name>")
    def get_recipe(name):
        try:
            path = recipe_path(name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not path.exists():
            return jsonify({"error": f"unknown recipe '{name}'"}), 404
        return jsonify(_plain(load_recipe_file(path)))

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
        try:
            path = recipe_path(name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not path.exists():
            return jsonify({"error": f"unknown recipe '{name}'"}), 404
        dump_recipe_file(body, path)
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
        try:
            path = recipe_path(name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if path.exists():
            return jsonify({"error": f"recipe '{name}' already exists"}), 409
        dump_recipe_file(config, path)
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

    # ----- knowledge graph -----

    @api.get("/api/v1/kg")
    def get_kg():
        kg = run_manager.knowledge_graph
        if kg is None:
            return jsonify({"error": "no run — the knowledge graph is built at run start"}), 404
        return jsonify(kg.to_node_link(
            node_type=request.args.get("type"),
            station=request.args.get("station"),
            edge=request.args.get("edge"),
        ))

    @api.post("/api/v1/kg/preview")
    def preview_kg():
        body = request.get_json(force=True, silent=True) or {}
        config = body.get("config")
        if not isinstance(config, dict):
            return jsonify({"error": "body must be {config: {...}}"}), 400
        name = body.get("name") or "draft"
        try:
            kg = build_knowledge_graph(config, name)
        except (KeyError, TypeError, AttributeError) as exc:
            return jsonify({"error": f"invalid config: {exc}"}), 400
        return jsonify(kg.to_node_link())

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
    """Flask app: REST blueprint + UI pages (+ chat when available)."""
    import secrets

    from simengine.api.chat import create_chat_blueprint
    from simengine.api.tools import ToolRegistry

    app = Flask(__name__, template_folder="ui", static_folder="ui/static", static_url_path="/static")
    app.secret_key = secrets.token_hex(32)  # per-process; chat session cookie
    app.register_blueprint(create_api_blueprint(run_manager))
    app.register_blueprint(create_chat_blueprint(ToolRegistry(run_manager)))

    @app.get("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/configure")
    def configure():
        return render_template("configure.html")

    @app.get("/comms")
    def comms():
        return render_template("comms.html")

    @app.get("/assistant")
    def assistant():
        return render_template("chat.html")

    return app
