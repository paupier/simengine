"""Gate P7.2 — tool registry + MCP server: every tool, error paths, 16 tools."""
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from simengine.api.tools import ToolRegistry
from simengine.engine.knowledge_graph import build_knowledge_graph
from simengine.engine.line import LineEngine
from simengine.runtime.run_manager import RunConflictError

PROJECT_CONFIG = Path(__file__).parents[1] / "config"


def demo_config():
    import yaml
    return yaml.safe_load(open(PROJECT_CONFIG / "scenarios.yaml"))["demo_line"]


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """ToolRegistry over a mocked run_manager with a live-ish snapshot + KG."""
    scenarios = tmp_path / "scenarios.yaml"
    shutil.copy(PROJECT_CONFIG / "scenarios.yaml", scenarios)
    recipes = tmp_path / "recipes"
    shutil.copytree(PROJECT_CONFIG / "recipes", recipes)
    monkeypatch.setenv("SIMENGINE_CONFIG_PATH", str(scenarios))
    monkeypatch.setenv("SIMENGINE_RECIPE_PATH", str(recipes))

    config = demo_config()
    engine = LineEngine(config, "demo_line", seed=1, run_id="mcp_test")
    for _ in range(30):
        engine.step()

    rm = MagicMock()
    rm.latest_snapshot = engine.snapshot()
    rm.knowledge_graph = build_knowledge_graph(config, "demo_line")
    rm.state = "RUNNING"
    rm.status.return_value = {"state": "RUNNING", "run_id": "mcp_test",
                              "scenario": "demo_line", "recipe": None,
                              "sim_time": 30.0, "step_count": 30}
    rm.start.return_value = "demo_line_20260719_000000"
    rm.start_recipe.return_value = "demo_line_20260719_000001"
    return ToolRegistry(rm), rm


class TestReadTools:
    def test_get_line_state(self, registry):
        reg, _ = registry
        state = reg.get_line_state()
        assert state["run_id"] == "mcp_test"
        assert "Press01" in state["stations"]

    def test_get_station(self, registry):
        reg, _ = registry
        st = reg.get_station("Press01")
        assert st["name"] == "Press01"
        with pytest.raises(ValueError, match="unknown station"):
            reg.get_station("Nope")

    def test_get_run_status(self, registry):
        reg, _ = registry
        assert reg.get_run_status()["state"] == "RUNNING"

    def test_query_knowledge_graph(self, registry):
        reg, _ = registry
        out = reg.query_knowledge_graph(node_type="Station")
        assert len(out["nodes"]) == 3

    def test_resolve_metric_with_live_value(self, registry):
        reg, _ = registry
        node = reg.resolve_metric("oil temperature on the press")
        assert node["id"] == "pv:Press01.OilTemp"
        assert isinstance(node["live_value"], float)
        assert set(node["addresses"]) == {
            "opcua_node_id", "sparkplug_metric", "mqtt_flat_topic", "rest_path"}

    def test_resolve_metric_no_match(self, registry):
        reg, _ = registry
        with pytest.raises(ValueError, match="nothing in the knowledge graph"):
            reg.resolve_metric("zzzz qqqq")

    def test_scenarios_and_recipes(self, registry):
        reg, _ = registry
        assert "demo_line" in reg.list_scenarios()
        assert reg.get_scenario("demo_line")["stations"][0]["name"] == "Press01"
        assert "quick_test" in reg.list_recipes()
        assert reg.get_recipe("quick_test")["base_scenario"] == "demo_line"
        with pytest.raises(ValueError):
            reg.get_scenario("nope")

    def test_explain_alarm(self, registry):
        reg, _ = registry
        fm = reg.explain_alarm("FM_BEARING_WEAR")
        assert fm["severity"] == "CRITICAL"
        assert "Press01" in fm["raised_by_stations"]
        pv = reg.explain_alarm("PV_OILTEMP_HIGH")
        assert pv["process_values"][0]["alarm_high"] == 68
        with pytest.raises(ValueError, match="unknown alarm code"):
            reg.explain_alarm("XX_NOPE")


class TestControlTools:
    def test_start_run(self, registry):
        reg, rm = registry
        out = reg.start_run("demo_line", seed=42)
        assert out["run_id"].startswith("demo_line_")
        rm.start.assert_called_once_with("demo_line", seed=42, speed_ratio=1.0)

    def test_start_run_conflict_is_tool_error(self, registry):
        reg, rm = registry
        rm.start.side_effect = RunConflictError("a run is already active")
        with pytest.raises(RunConflictError, match="already active"):
            reg.start_run("demo_line")

    def test_stop_run(self, registry):
        reg, rm = registry
        assert reg.stop_run() == {"stopped": True}
        rm.stop.assert_called_once()

    def test_stop_without_run(self, registry):
        reg, rm = registry
        rm.state = "IDLE"
        with pytest.raises(RuntimeError, match="no active run"):
            reg.stop_run()

    def test_update_scenario_valid(self, registry):
        reg, _ = registry
        import yaml
        cfg = reg.get_scenario("two_station_minimal")
        cfg["stations"][0]["cycle_time"] = 9.0
        out = reg.update_scenario("two_station_minimal", yaml.safe_dump(cfg))
        assert out["updated"] == "two_station_minimal"
        assert reg.get_scenario("two_station_minimal")["stations"][0]["cycle_time"] == 9.0

    def test_update_scenario_invalid_yaml_leaves_file(self, registry):
        reg, _ = registry
        before = reg.get_scenario("two_station_minimal")
        with pytest.raises(ValueError, match="invalid YAML"):
            reg.update_scenario("two_station_minimal", "{unbalanced: [")
        with pytest.raises(ValueError, match="at least 2 stations"):
            reg.update_scenario("two_station_minimal",
                                "stations:\n  - {name: only, cycle_time: 1}\nbuffers: []\n")
        assert reg.get_scenario("two_station_minimal") == before

    def test_update_recipe_invalid_leaves_file(self, registry):
        reg, _ = registry
        before = reg.get_recipe("quick_test")
        with pytest.raises(ValueError):
            reg.update_recipe("quick_test", "name: X\n")  # missing base/segments
        assert reg.get_recipe("quick_test") == before

    def test_set_comms(self, registry):
        reg, _ = registry
        out = reg.set_comms("demo_line", {"opcua": {"enabled": True, "port": 4841}})
        assert out["applies"] == "next_run"
        assert reg.get_scenario("demo_line")["comms"]["opcua"]["port"] == 4841
        with pytest.raises(ValueError):
            reg.set_comms("demo_line", {"opcua": {"enabled": True, "port": 99999}})


class TestNoRunErrors:
    def test_state_tools_error_without_run(self, registry):
        reg, rm = registry
        rm.latest_snapshot = None
        rm.knowledge_graph = None
        with pytest.raises(RuntimeError, match="no run active"):
            reg.get_line_state()
        with pytest.raises(RuntimeError, match="knowledge graph"):
            reg.resolve_metric("anything at all")


class TestMcpServer:
    def test_sixteen_tools_registered(self, registry):
        reg, _ = registry
        from simengine.api.mcp_server import create_mcp_server
        import asyncio
        mcp = create_mcp_server(reg, port=8766)
        listed = asyncio.new_event_loop().run_until_complete(mcp.list_tools())
        names = {t.name for t in listed}
        assert len(names) == 16
        assert names == set(reg.READ_TOOLS) | set(reg.CONTROL_TOOLS)


class TestPathTraversal:
    """Recipe names are user/LLM-supplied — must not escape the recipes dir."""

    BAD_NAMES = ["../scenarios", "../../etc/passwd", "..", "a/../../b",
                 "/etc/passwd", ".hidden", ""]

    def test_get_recipe_rejects_traversal(self, registry):
        reg, _ = registry
        for bad in self.BAD_NAMES:
            with pytest.raises(ValueError, match="invalid recipe name"):
                reg.get_recipe(bad)

    def test_update_recipe_rejects_traversal(self, registry, tmp_path):
        reg, _ = registry
        outside = tmp_path / "scenarios.yaml"
        before = outside.read_text()
        valid = ("name: X\nbase_scenario: demo_line\n"
                 "segments:\n  - {name: S, quantity: 1}\n")
        with pytest.raises(ValueError, match="invalid recipe name"):
            reg.update_recipe("../scenarios", valid)
        assert outside.read_text() == before  # file untouched

    def test_start_recipe_rejects_traversal(self, registry):
        from simengine.runtime.recipe_runner import load_recipe_config
        with pytest.raises(ValueError, match="invalid recipe name"):
            load_recipe_config("../scenarios")

    def test_rest_recipe_traversal_rejected(self, registry, tmp_path, monkeypatch):
        from simengine.api.rest import create_app
        from simengine.runtime.run_manager import RunManager
        app = create_app(RunManager())
        app.config["TESTING"] = True
        client = app.test_client()
        # Flask blocks '/' in <name>; dotfile/.. stems must 400 too
        r = client.put("/api/v1/recipes/..%2F..%2Fscenarios",
                       json={"name": "X", "base_scenario": "demo_line",
                             "segments": [{"name": "S", "quantity": 1}]})
        assert r.status_code in (400, 404)
        r2 = client.post("/api/v1/recipes",
                         json={"name": "../evil",
                               "config": {"name": "X", "base_scenario": "demo_line",
                                          "segments": [{"name": "S", "quantity": 1}]}})
        assert r2.status_code == 400
        assert "invalid recipe name" in r2.get_json()["error"]
