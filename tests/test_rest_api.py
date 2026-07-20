"""Gate P4 — REST API: CRUD, run lifecycle, 409 double-start (Flask test client)."""
import shutil
import time
from pathlib import Path

import pytest

from simengine.api.rest import create_app
from simengine.runtime.run_manager import RunManager

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT_CONFIG = Path(__file__).parents[1] / "config"


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    """Isolated copies of the shipped scenario/recipe files + fresh app."""
    scenarios = tmp_path / "scenarios.yaml"
    shutil.copy(PROJECT_CONFIG / "scenarios.yaml", scenarios)
    recipes_dir = tmp_path / "recipes"
    shutil.copytree(PROJECT_CONFIG / "recipes", recipes_dir)
    monkeypatch.setenv("SIMENGINE_CONFIG_PATH", str(scenarios))
    monkeypatch.setenv("SIMENGINE_RECIPE_PATH", str(recipes_dir))

    run_manager = RunManager()
    app = create_app(run_manager)
    app.config["TESTING"] = True
    yield app.test_client(), run_manager
    run_manager.stop()


def no_opcua(config):
    config["comms"] = {"opcua": {"enabled": False}}
    return config


@pytest.fixture
def client(api_env, monkeypatch):
    """Test client with OPC UA disabled (no sockets in unit tests)."""
    client, run_manager = api_env
    # disable the OPC UA publisher for all scenarios in the temp file
    import yaml
    from simengine.config.loader import get_config_path
    path = get_config_path()
    data = yaml.safe_load(open(path))
    for cfg in data.values():
        cfg["comms"] = {"opcua": {"enabled": False}}
    yaml.safe_dump(data, open(path, "w"), sort_keys=False)
    return client


class TestScenarioCRUD:
    def test_list(self, client):
        names = client.get("/api/v1/scenarios").get_json()
        assert "demo_line" in names and "press_line_8" in names

    def test_get(self, client):
        cfg = client.get("/api/v1/scenarios/demo_line").get_json()
        assert cfg["stations"][0]["name"] == "Press01"

    def test_get_unknown_404(self, client):
        assert client.get("/api/v1/scenarios/nope").status_code == 404

    def test_put_valid(self, client):
        cfg = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        cfg["stations"][0]["cycle_time"] = 7.5
        r = client.put("/api/v1/scenarios/two_station_minimal", json=cfg)
        assert r.status_code == 200
        cfg2 = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        assert cfg2["stations"][0]["cycle_time"] == 7.5

    def test_put_invalid_400_leaves_file(self, client):
        before = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        bad = {"stations": [{"name": "only_one", "cycle_time": 1}], "buffers": []}
        r = client.put("/api/v1/scenarios/two_station_minimal", json=bad)
        assert r.status_code == 400
        assert "at least 2 stations" in r.get_json()["error"]
        after = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        assert after == before

    def test_post_create(self, client):
        cfg = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        r = client.post("/api/v1/scenarios", json={"name": "created_line", "config": cfg})
        assert r.status_code == 201
        assert "created_line" in client.get("/api/v1/scenarios").get_json()

    def test_post_duplicate_409(self, client):
        cfg = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        r = client.post("/api/v1/scenarios", json={"name": "demo_line", "config": cfg})
        assert r.status_code == 409


class TestRecipeCRUD:
    def test_list(self, client):
        names = client.get("/api/v1/recipes").get_json()
        assert "quick_test" in names

    def test_get(self, client):
        cfg = client.get("/api/v1/recipes/quick_test").get_json()
        assert cfg["base_scenario"] == "demo_line"

    def test_put_invalid_400(self, client):
        r = client.put("/api/v1/recipes/quick_test", json={"name": "X"})
        assert r.status_code == 400

    def test_post_create(self, client):
        cfg = client.get("/api/v1/recipes/quick_test").get_json()
        r = client.post("/api/v1/recipes", json={"name": "new_recipe", "config": cfg})
        assert r.status_code == 201
        assert "new_recipe" in client.get("/api/v1/recipes").get_json()


class TestCommsEndpoint:
    def test_get_requires_scenario(self, client):
        assert client.get("/api/v1/comms").status_code == 400

    def test_put_and_get(self, client):
        comms = {
            "opcua": {"enabled": True, "port": 4841},
            "opcua_mqtt": {"enabled": False},
            "sparkplugb": {"enabled": False},
        }
        r = client.put("/api/v1/comms", json={"scenario": "demo_line", "comms": comms})
        assert r.status_code == 200
        assert r.get_json()["applies"] == "next_run"
        got = client.get("/api/v1/comms?scenario=demo_line").get_json()
        assert got["opcua"]["port"] == 4841

    def test_put_invalid_400(self, client):
        comms = {"opcua_mqtt": {"enabled": True, "broker": "tcp://x:1"}}
        r = client.put("/api/v1/comms", json={"scenario": "demo_line", "comms": comms})
        assert r.status_code == 400


class TestRunLifecycle:
    def wait_for_snapshot(self, client, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = client.get("/api/v1/state")
            if r.status_code == 200:
                return r.get_json()
            time.sleep(0.05)
        raise AssertionError("no snapshot within timeout")

    def test_full_lifecycle(self, client):
        r = client.post("/api/v1/runs",
                        json={"scenario": "two_station_minimal", "seed": 42,
                              "speed_ratio": 1000.0})
        assert r.status_code == 201
        run_id = r.get_json()["run_id"]
        assert run_id.startswith("two_station_minimal_")

        snap = self.wait_for_snapshot(client)
        assert snap["run_id"] == run_id
        assert set(snap["stations"].keys()) == {"S1", "S2"}

        st = client.get("/api/v1/state/stations/S1")
        assert st.status_code == 200
        assert st.get_json()["name"] == "S1"
        assert client.get("/api/v1/state/stations/NOPE").status_code == 404

        cur = client.get("/api/v1/runs/current").get_json()
        assert cur["state"] == "RUNNING"
        assert cur["run_id"] == run_id

        # 409 double start
        r2 = client.post("/api/v1/runs", json={"scenario": "demo_line"})
        assert r2.status_code == 409

        r3 = client.delete("/api/v1/runs/current")
        assert r3.status_code == 200
        deadline = time.time() + 5
        while time.time() < deadline:
            if client.get("/api/v1/runs/current").get_json()["state"] == "IDLE":
                break
            time.sleep(0.05)
        assert client.get("/api/v1/runs/current").get_json()["state"] == "IDLE"

    def test_stop_without_run_409(self, client):
        assert client.delete("/api/v1/runs/current").status_code == 409

    def test_unknown_scenario_400(self, client):
        r = client.post("/api/v1/runs", json={"scenario": "nope"})
        assert r.status_code == 400

    def test_state_404_before_any_run(self, client):
        assert client.get("/api/v1/state").status_code == 404


class TestKGPreview:
    def test_preview_matches_scenario_stations(self, client):
        cfg = client.get("/api/v1/scenarios/demo_line").get_json()
        r = client.post("/api/v1/kg/preview", json={"config": cfg, "name": "demo_line"})
        assert r.status_code == 200
        data = r.get_json()
        station_names = {n["name"] for n in data["nodes"] if n["type"] == "Station"}
        assert station_names == {"Press01", "Weld02", "Pack03"}

    def test_preview_requires_no_active_run(self, client):
        # No run has been started anywhere in this test — proves the pure-function path.
        cfg = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        r = client.post("/api/v1/kg/preview", json={"config": cfg})
        assert r.status_code == 200
        assert len(r.get_json()["nodes"]) > 0

    def test_preview_deterministic(self, client):
        cfg = client.get("/api/v1/scenarios/demo_line").get_json()
        r1 = client.post("/api/v1/kg/preview", json={"config": cfg, "name": "x"})
        r2 = client.post("/api/v1/kg/preview", json={"config": cfg, "name": "x"})
        assert r1.get_json() == r2.get_json()

    def test_preview_missing_config_400(self, client):
        r = client.post("/api/v1/kg/preview", json={})
        assert r.status_code == 400

    def test_preview_invalid_config_400(self, client):
        r = client.post("/api/v1/kg/preview", json={"config": {"stations": "not-a-list"}})
        assert r.status_code == 400


class TestMisc:
    def test_healthz(self, client):
        data = client.get("/healthz").get_json()
        assert data["status"] == "ok"

    def test_plugins(self, client):
        data = client.get("/api/v1/plugins").get_json()
        assert "historian-influx" in data

    def test_ui_pages_render(self, client):
        for path in ("/", "/configure", "/comms"):
            r = client.get(path)
            assert r.status_code == 200
            assert b"simengine" in r.data
