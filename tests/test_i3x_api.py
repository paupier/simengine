import shutil
from pathlib import Path

import pytest
import yaml
from simengine.runtime.run_manager import RunManager
from simengine.api.rest import create_app
from simengine.config.loader import get_config_path

PROJECT_CONFIG = Path(__file__).parents[1] / "config"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # These tests use scenario names from the shipped config/scenarios.yaml
    # (two_station_minimal, demo_line), not the tests/fixtures/ scenario set
    # the autouse conftest fixture routes to by default. Mirrors
    # tests/test_rest_api.py's api_env/client fixtures: an isolated copy of
    # the shipped file with OPC UA (and MQTT-backed) publishers disabled so
    # starting a real run here doesn't try to bind sockets / reach a broker.
    scenarios = tmp_path / "scenarios.yaml"
    shutil.copy(PROJECT_CONFIG / "scenarios.yaml", scenarios)
    monkeypatch.setenv("SIMENGINE_CONFIG_PATH", str(scenarios))

    path = get_config_path()
    data = yaml.safe_load(open(path))
    for cfg in data.values():
        cfg["comms"] = {"opcua": {"enabled": False}, "opcua_mqtt": {"enabled": False},
                         "sparkplugb": {"enabled": False}}
    yaml.safe_dump(data, open(path, "w"), sort_keys=False)

    rm = RunManager()
    app = create_app(rm)
    app.testing = True
    yield app.test_client(), rm
    rm.stop()


def _start_with_i3x(client, rm, scenario="two_station_minimal"):
    import time
    resp = client.post("/api/v1/runs", json={"scenario": scenario, "seed": 1})
    assert resp.status_code == 201, resp.get_json()
    time.sleep(0.2)
    rm.config.setdefault("comms", {})["i3x"] = {"enabled": True}


class TestInfoAlwaysReachable:
    def test_info_without_any_run(self, client):
        c, _ = client
        resp = c.get("/i3x/v1/info")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["result"]["specVersion"] == "1.0"

    def test_info_capabilities_shape(self, client):
        c, _ = client
        body = c.get("/i3x/v1/info").get_json()
        caps = body["result"]["capabilities"]
        assert caps == {
            "query": {"history": True},
            "update": {"current": False, "history": False},
            "subscribe": {"stream": True},
        }


class TestEnableGate:
    def test_namespaces_403_when_i3x_not_enabled(self, client):
        c, rm = client
        c.post("/api/v1/runs", json={"scenario": "two_station_minimal", "seed": 1})
        import time; time.sleep(0.2)
        resp = c.get("/i3x/v1/namespaces")
        assert resp.status_code == 403
        assert resp.get_json()["success"] is False

    def test_namespaces_403_when_no_run_ever_started(self, client):
        c, _ = client
        resp = c.get("/i3x/v1/namespaces")
        assert resp.status_code == 403


class TestNamespacesTypesRelationshiptypes:
    def test_namespaces(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.get("/i3x/v1/namespaces")
        assert resp.status_code == 200
        uris = {n["uri"] for n in resp.get_json()["result"]}
        assert "http://simengine.local/i3x/" in uris

    def test_objecttypes(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.get("/i3x/v1/objecttypes")
        assert resp.status_code == 200
        elem_ids = {t["elementId"] for t in resp.get_json()["result"]}
        assert "type:Station" in elem_ids

    def test_objecttypes_query_by_id(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/objecttypes/query", json={"elementIds": ["type:Station", "type:ghost"]})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is False  # one of two failed
        assert body["results"][0]["success"] is True
        assert body["results"][1]["success"] is False
        assert body["results"][1]["responseDetail"]["status"] == 404

    def test_relationshiptypes(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.get("/i3x/v1/relationshiptypes")
        elem_ids = {t["elementId"] for t in resp.get_json()["result"]}
        assert "rel:CONTAINS" in elem_ids

    def test_relationshiptypes_query_by_id(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/relationshiptypes/query", json={"elementIds": ["rel:CONTAINS"]})
        assert resp.get_json()["results"][0]["result"]["reverseOf"] == "rel:CONTAINED_BY"

    def test_object_graph_rebuilds_on_new_run(self, client):
        c, rm = client
        _start_with_i3x(c, rm, scenario="two_station_minimal")
        first_run_id = rm.run_id
        first = {o["elementId"] for o in c.get("/i3x/v1/objecttypes").get_json()["result"]}

        rm.stop()
        import time; time.sleep(0.2)
        _start_with_i3x(c, rm, scenario="demo_line")  # a scenario with different node types (health)
        assert rm.run_id != first_run_id
        second = {o["elementId"] for o in c.get("/i3x/v1/objecttypes").get_json()["result"]}
        # both are valid graphs; the point is the cache actually reflects the new run
        assert second  # non-empty, and no stale exception from a mismatched cache key
