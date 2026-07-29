import shutil
import time
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


def _start_with_i3x(client, rm, scenario="two_station_minimal", speed_ratio=1.0):
    import time
    resp = client.post("/api/v1/runs", json={"scenario": scenario, "seed": 1, "speed_ratio": speed_ratio})
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
        # Prove the cache actually picked up the new run's graph, not just that
        # it's non-empty (which a stale cache would also satisfy):
        # demo_line's Press01 has a failure_modes block -- two_station_minimal
        # has no health config at all -- so "type:FailureMode" is a
        # scenario-specific fingerprint that must appear in the new graph and
        # must not have been present in the old one.
        assert "type:FailureMode" not in first
        assert "type:FailureMode" in second
        assert second != first


class TestObjects:
    def test_get_objects_returns_full_list(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.get("/i3x/v1/objects")
        assert resp.status_code == 200
        elem_ids = {o["elementId"] for o in resp.get_json()["result"]}
        assert "station:S1" in elem_ids

    def test_objects_list_by_id(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/objects/list", json={"elementIds": ["station:S1", "ghost"]})
        body = resp.get_json()
        assert body["results"][0]["success"] is True
        assert body["results"][1]["success"] is False


class TestObjectsRelated:
    def test_related_returns_neighbors(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/objects/related", json={"elementIds": ["station:S1"]})
        body = resp.get_json()
        assert body["results"][0]["success"] is True
        related = body["results"][0]["result"]
        assert isinstance(related, list) and len(related) > 0
        assert "sourceRelationship" in related[0]
        assert "object" in related[0]


class TestObjectsValue:
    def test_value_for_metric_while_running(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/objects/value", json={"elementIds": ["metric:S1.State"]})
        body = resp.get_json()
        result = body["results"][0]["result"]
        assert result["quality"] == "Good"
        assert result["value"] in ("IDLE", "PROCESSING", "BLOCKED", "STARVED", "DEGRADED", "FAILED", "UNDER_REPAIR")
        assert "timestamp" in result

    def test_value_no_run_is_good_no_data(self, client):
        c, rm = client
        c.post("/api/v1/runs", json={"scenario": "two_station_minimal", "seed": 1})
        import time; time.sleep(0.2)
        rm.config.setdefault("comms", {})["i3x"] = {"enabled": True}
        rm.stop()
        import time; time.sleep(0.2)
        resp = c.post("/i3x/v1/objects/value", json={"elementIds": ["metric:S1.State"]})
        result = resp.get_json()["results"][0]["result"]
        assert result["quality"] == "GoodNoData"

    def test_value_for_unknown_element_404s_in_bulk_result(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/objects/value", json={"elementIds": ["metric:ghost"]})
        result = resp.get_json()["results"][0]
        assert result["success"] is False
        assert result["responseDetail"]["status"] == 404

    def test_value_for_structural_node_is_composition_with_no_value(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/objects/value", json={"elementIds": ["station:S1"]})
        result = resp.get_json()["results"][0]["result"]
        # two_station_minimal's S1 has no process_values configured, so it
        # carries no HAS_PV edge and isComposition is correctly False here
        # (see engine/knowledge_graph.py's HAS_PV edge construction and
        # i3x_build.py's _is_composition) -- the point under test is that a
        # structural node's value/quality resolve to None/GoodNoData
        # regardless of its isComposition flag.
        assert result["isComposition"] is False
        assert result["value"] is None
        assert result["quality"] == "GoodNoData"


class TestNoWriteRoutes:
    def test_put_object_value_is_not_registered(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.put("/i3x/v1/objects/value", json={"updates": []})
        assert resp.status_code in (404, 405)  # Flask's default for an unregistered route/method

    def test_put_object_history_is_not_registered(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.put("/i3x/v1/objects/history", json={"updates": []})
        assert resp.status_code in (404, 405)


class TestObjectsHistory:
    def test_history_empty_without_historian(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/objects/history", json={
            "elementIds": ["metric:S1.State"],
            "startTime": "2026-01-01T00:00:00Z", "endTime": "2026-01-02T00:00:00Z",
        })
        result = resp.get_json()["results"][0]["result"]
        assert result["values"] == []


class TestSubscriptionCrud:
    def test_create_then_register_then_list(self, client):
        c, rm = client
        _start_with_i3x(c, rm)

        created = c.post("/i3x/v1/subscriptions",
                         json={"clientId": "test-client", "displayName": "watch S1"}).get_json()
        assert created["success"] is True
        sub_id = created["result"]["subscriptionId"]

        reg = c.post("/i3x/v1/subscriptions/register", json={
            "clientId": "test-client", "subscriptionId": sub_id, "elementIds": ["metric:S1.State"],
        }).get_json()
        assert reg["results"][0]["success"] is True

        listed = c.post("/i3x/v1/subscriptions/list",
                        json={"clientId": "test-client", "subscriptionIds": [sub_id]}).get_json()
        assert listed["results"][0]["result"]["monitoredObjects"] == [{"elementId": "metric:S1.State"}]

    def test_register_unknown_element_404s(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        sub_id = c.post("/i3x/v1/subscriptions", json={"clientId": "c1"}).get_json()["result"]["subscriptionId"]
        resp = c.post("/i3x/v1/subscriptions/register",
                      json={"clientId": "c1", "subscriptionId": sub_id, "elementIds": ["ghost"]})
        assert resp.get_json()["results"][0]["responseDetail"]["status"] == 404

    def test_register_on_missing_subscription_404s(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/register",
                      json={"clientId": "c1", "subscriptionId": "no-such-sub", "elementIds": ["metric:S1.State"]})
        assert resp.status_code == 404

    def test_delete_subscription(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        sub_id = c.post("/i3x/v1/subscriptions", json={"clientId": "c1"}).get_json()["result"]["subscriptionId"]
        resp = c.post("/i3x/v1/subscriptions/delete", json={"clientId": "c1", "subscriptionIds": [sub_id]})
        assert resp.get_json()["results"][0]["success"] is True
        listed = c.post("/i3x/v1/subscriptions/list", json={"clientId": "c1", "subscriptionIds": [sub_id]}).get_json()
        assert listed["results"][0]["success"] is False


class TestSubscriptionMissingFields:
    def test_create_missing_clientId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions", json={})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "clientId" in body["responseDetail"]["detail"]

    def test_register_missing_clientId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/register", json={"subscriptionId": "sid"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "clientId" in body["responseDetail"]["detail"]

    def test_register_missing_subscriptionId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/register", json={"clientId": "c1"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "subscriptionId" in body["responseDetail"]["detail"]

    def test_unregister_missing_clientId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/unregister", json={"subscriptionId": "sid"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "clientId" in body["responseDetail"]["detail"]

    def test_unregister_missing_subscriptionId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/unregister", json={"clientId": "c1"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "subscriptionId" in body["responseDetail"]["detail"]

    def test_delete_missing_clientId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/delete", json={})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "clientId" in body["responseDetail"]["detail"]

    def test_list_missing_clientId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/list", json={})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "clientId" in body["responseDetail"]["detail"]

    def test_sync_missing_clientId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/sync", json={"subscriptionId": "sid"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "clientId" in body["responseDetail"]["detail"]

    def test_sync_missing_subscriptionId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/sync", json={"clientId": "c1"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "subscriptionId" in body["responseDetail"]["detail"]

    def test_stream_missing_clientId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/stream", json={"subscriptionId": "sid"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "clientId" in body["responseDetail"]["detail"]

    def test_stream_missing_subscriptionId(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/stream", json={"clientId": "c1"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "subscriptionId" in body["responseDetail"]["detail"]


class TestSync:
    def test_sync_receives_updates_after_polling_interval(self, client):
        c, rm = client
        # Default speed_ratio=1.0 means one sim step per wall-clock second
        # (see run_manager.run_segment: step_wall = sim_step / speed_ratio).
        # The poll worker is a module-level singleton started at blueprint-
        # creation time (well before this test's run/registration exist), so
        # by the time _start_with_i3x's 0.2s sleep elapses it has typically
        # already observed the run's near-instant first step (engine.step()
        # runs before run_segment's first wall-clock sleep) and recorded that
        # step_count as "last seen" -- before any element is registered here.
        # The *next* observable change then requires a full ~1s wall-clock
        # step, which a fixed 0.5s post-registration sleep can't reliably
        # cover. Using a fast speed_ratio (matching test_rest_api.py's
        # established pattern for tests needing rapid step cadence) ensures a
        # step_count change lands well within the 0.5s window regardless of
        # exactly when the poll worker's own 0.2s cycle happens to fall.
        _start_with_i3x(c, rm, speed_ratio=1000.0)
        sub_id = c.post("/i3x/v1/subscriptions", json={"clientId": "c1"}).get_json()["result"]["subscriptionId"]
        c.post("/i3x/v1/subscriptions/register",
              json={"clientId": "c1", "subscriptionId": sub_id, "elementIds": ["metric:S1.State"]})

        time.sleep(0.5)  # let the poll worker observe at least one step_count change

        resp = c.post("/i3x/v1/subscriptions/sync",
                      json={"clientId": "c1", "subscriptionId": sub_id, "lastSequenceNumber": None})
        body = resp.get_json()
        assert body["success"] is True
        assert len(body["result"]) >= 1
        assert body["result"][0]["updates"][0]["elementId"] == "metric:S1.State"

    def test_sync_on_missing_subscription_404s(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/sync",
                      json={"clientId": "c1", "subscriptionId": "no-such-sub", "lastSequenceNumber": None})
        assert resp.status_code == 404


class TestStream:
    def test_stream_emits_at_least_one_sse_event(self, client):
        c, rm = client
        # See TestSync.test_sync_receives_updates_after_polling_interval for
        # why a fast speed_ratio is needed here, not a longer sleep.
        _start_with_i3x(c, rm, speed_ratio=1000.0)
        sub_id = c.post("/i3x/v1/subscriptions", json={"clientId": "c1"}).get_json()["result"]["subscriptionId"]
        c.post("/i3x/v1/subscriptions/register",
              json={"clientId": "c1", "subscriptionId": sub_id, "elementIds": ["metric:S1.State"]})
        time.sleep(0.5)

        resp = c.post("/i3x/v1/subscriptions/stream", json={"clientId": "c1", "subscriptionId": sub_id})
        assert resp.mimetype == "text/event-stream"
        # Flask's test client buffers the generator eagerly; take the first chunk.
        chunk = next(resp.response)
        assert b"data:" in chunk
        assert b"metric:S1.State" in chunk

    def test_stream_on_missing_subscription_404s(self, client):
        c, rm = client
        _start_with_i3x(c, rm)
        resp = c.post("/i3x/v1/subscriptions/stream", json={"clientId": "c1", "subscriptionId": "no-such-sub"})
        assert resp.status_code == 404
