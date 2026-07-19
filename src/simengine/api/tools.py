"""Tool registry — one implementation, three surfaces (AI interface spec §2).

Every tool is a thin wrapper over the same functions the REST API calls.
The MCP server registers these callables directly; the embedded chat calls
them as plain function references. Errors are raised as ValueError /
RuntimeError with actionable messages — MCP and the chat surface them as
tool errors; config files are never touched on validation failure.

Control tools are always available (design decision): anything that can reach
the MCP port can start/stop runs and edit configs, exactly like the REST port.
"""
from dataclasses import asdict
from typing import Optional

import yaml as pyyaml

from simengine.api import config_files
from simengine.config.loader import (
    get_recipes_dir,
    validate_comms,
    validate_serial_topology,
)
from simengine.runtime.recipe_runner import parse_recipe, validate_recipe
from simengine.runtime.run_manager import RunManager


class ToolRegistry:
    """All MCP/chat tools bound to one RunManager."""

    def __init__(self, run_manager: RunManager):
        self.run_manager = run_manager

    # ------------------------------------------------------------------
    # Read tools
    # ------------------------------------------------------------------

    def get_line_state(self) -> dict:
        """Full line snapshot: KPIs, per-station state/health/process values/alarms, buffers."""
        snap = self.run_manager.latest_snapshot
        if snap is None:
            raise RuntimeError("no run active — start one with start_run")
        return asdict(snap)

    def get_station(self, name: str) -> dict:
        """One station's snapshot: state, health, counters, OEE, process values, alarms."""
        snap = self.run_manager.latest_snapshot
        if snap is None:
            raise RuntimeError("no run active — start one with start_run")
        st = snap.stations.get(name)
        if st is None:
            raise ValueError(
                f"unknown station '{name}' — stations: {sorted(snap.stations)}")
        return asdict(st)

    def get_run_status(self) -> dict:
        """Run status: run_id, scenario, sim_time, RUNNING/IDLE."""
        return self.run_manager.status()

    def query_knowledge_graph(self, node_type: Optional[str] = None,
                              name: Optional[str] = None,
                              relation: Optional[str] = None) -> dict:
        """Query the knowledge graph: filter nodes by type/name, edges by relation."""
        kg = self._kg()
        nodes = kg.find_nodes(node_type=node_type, name=name)
        edges = kg.find_edges(edge_type=relation)
        if node_type or name:
            ids = {n["id"] for n in nodes}
            edges = [e for e in edges if e["source"] in ids or e["target"] in ids]
        return {"nodes": nodes, "edges": edges}

    def resolve_metric(self, query: str) -> dict:
        """Semantic lookup ("oil temperature on the press") -> KG node with all
        protocol addresses plus the current live value."""
        kg = self._kg()
        matches = kg.resolve(query)
        if not matches:
            raise ValueError(f"nothing in the knowledge graph matches {query!r}")
        node = dict(matches[0])
        node["live_value"] = self._live_value(node)
        return node

    def list_scenarios(self) -> list:
        """List available scenario names."""
        data, _ = config_files.load_scenarios_file()
        return sorted(data.keys())

    def get_scenario(self, name: str) -> dict:
        """Full configuration of one scenario."""
        data, _ = config_files.load_scenarios_file()
        if name not in data:
            raise ValueError(f"unknown scenario '{name}'")
        return config_files.plain(data[name])

    def list_recipes(self) -> list:
        """List available recipe names."""
        return sorted(p.stem for p in get_recipes_dir().glob("*.yaml"))

    def get_recipe(self, name: str) -> dict:
        """Full configuration of one recipe."""
        path = config_files.recipe_path(name)
        if not path.exists():
            raise ValueError(f"unknown recipe '{name}'")
        return config_files.plain(config_files.load_recipe_file(path))

    def explain_alarm(self, code: str) -> dict:
        """Alarm catalog entry + knowledge-graph context: which stations raise
        it and, for PV alarms, the configured thresholds."""
        kg = self._kg()
        code = code.upper()
        node = kg.nodes.get(f"alarm:{code}")
        if node is None:
            known = sorted(n["name"] for n in kg.find_nodes("AlarmCode"))
            raise ValueError(f"unknown alarm code '{code}' — known: {known}")
        raised_by = [n["name"] for n in kg.neighbors(f"alarm:{code}", "CAN_RAISE")]
        context = {"code": code, "severity": node["severity"],
                   "raised_by_stations": raised_by}
        if code.startswith("PV_"):
            pvs = [n for n in kg.find_nodes("ProcessValue")
                   if code in n.get("alarm_codes", [])]
            context["process_values"] = [
                {"station": n["station"], "name": n["name"], "unit": n["unit"],
                 "alarm_high": n.get("alarm_high"), "alarm_low": n.get("alarm_low")}
                for n in pvs]
        elif code.startswith("FM_"):
            context["failure_modes"] = [
                {"station": n["station"], "name": n["name"],
                 "failure_type": n["failure_type"]}
                for n in kg.find_nodes("FailureMode")
                if n.get("alarm_code") == code]
        return context

    # ------------------------------------------------------------------
    # Control tools (always on)
    # ------------------------------------------------------------------

    def start_run(self, scenario: str, seed: Optional[int] = None,
                  speed_ratio: float = 1.0) -> dict:
        """Start a scenario run. Errors if a run is already active."""
        run_id = self.run_manager.start(scenario, seed=seed,
                                        speed_ratio=speed_ratio)
        return {"run_id": run_id}

    def start_recipe(self, recipe: str, seed: Optional[int] = None) -> dict:
        """Start a multi-segment recipe run. Errors if a run is already active."""
        run_id = self.run_manager.start_recipe(recipe, seed=seed)
        return {"run_id": run_id}

    def stop_run(self) -> dict:
        """Gracefully stop the active run."""
        if self.run_manager.state == "IDLE":
            raise RuntimeError("no active run to stop")
        self.run_manager.stop()
        return {"stopped": True}

    def update_scenario(self, name: str, yaml_text: str) -> dict:
        """Replace a scenario's YAML config. The full validator suite runs
        before writing — invalid input leaves the file untouched."""
        try:
            body = pyyaml.safe_load(yaml_text)
        except pyyaml.YAMLError as exc:
            raise ValueError(f"invalid YAML: {exc}")
        if not isinstance(body, dict):
            raise ValueError("scenario YAML must be a mapping")
        validate_serial_topology(body)  # raises ValueError, file untouched
        data, path = config_files.load_scenarios_file()
        if name not in data:
            raise ValueError(f"unknown scenario '{name}'")
        data[name] = body
        config_files.dump_scenarios_file(data, path)
        return {"updated": name, "applies": "next_run"}

    def update_recipe(self, name: str, yaml_text: str) -> dict:
        """Replace a recipe's YAML config. Validators run before writing."""
        try:
            body = pyyaml.safe_load(yaml_text)
        except pyyaml.YAMLError as exc:
            raise ValueError(f"invalid YAML: {exc}")
        if not isinstance(body, dict):
            raise ValueError("recipe YAML must be a mapping")
        recipe = parse_recipe(body)
        validate_recipe(recipe)
        path = config_files.recipe_path(name)
        if not path.exists():
            raise ValueError(f"unknown recipe '{name}'")
        config_files.dump_recipe_file(body, path)
        return {"updated": name}

    def set_comms(self, scenario: str, comms: dict) -> dict:
        """Update a scenario's comms block (opcua / opcua_mqtt / sparkplugb).
        Applies at the next run start."""
        validate_comms({"comms": comms})
        data, path = config_files.load_scenarios_file()
        if scenario not in data:
            raise ValueError(f"unknown scenario '{scenario}'")
        data[scenario]["comms"] = comms
        config_files.dump_scenarios_file(data, path)
        return {"updated": scenario, "applies": "next_run"}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    READ_TOOLS = ("get_line_state", "get_station", "get_run_status",
                  "query_knowledge_graph", "resolve_metric", "list_scenarios",
                  "get_scenario", "list_recipes", "get_recipe", "explain_alarm")
    CONTROL_TOOLS = ("start_run", "start_recipe", "stop_run",
                     "update_scenario", "update_recipe", "set_comms")

    def all_tools(self):
        """[(name, bound callable)] for MCP registration / chat wiring."""
        return [(name, getattr(self, name))
                for name in self.READ_TOOLS + self.CONTROL_TOOLS]

    def _kg(self):
        kg = self.run_manager.knowledge_graph
        if kg is None:
            raise RuntimeError(
                "no knowledge graph — it is built at run start; start a run first")
        return kg

    def _live_value(self, node: dict):
        snap = self.run_manager.latest_snapshot
        if snap is None:
            return None
        station = snap.stations.get(node.get("station", ""))
        if station is None:
            return None
        if node["type"] == "ProcessValue":
            for pv in station.process_values:
                if pv.name == node["name"]:
                    return pv.value
        elif node["type"] == "Metric":
            field_map = {
                "State": station.state, "Health": station.health,
                "PartsMade": station.parts_made, "Good": station.good,
                "Scrap": station.scrap, "OEE": station.oee,
                "Availability": station.availability,
                "Performance": station.performance, "Quality": station.quality,
            }
            return field_map.get(node["name"])
        return None
