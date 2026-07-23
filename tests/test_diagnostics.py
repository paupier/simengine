"""Gate — Diagnostics: raw MQTT one-shot publish + REST GET/PUT scratch
value, both independent of the engine/publisher stack (Flask test client)."""
from unittest.mock import patch

import pytest

from simengine.api import diagnostics
from simengine.api.rest import create_app
from simengine.runtime.run_manager import RunManager


@pytest.fixture(autouse=True)
def reset_diagnostics_value():
    diagnostics._state["value"] = None
    yield
    diagnostics._state["value"] = None


@pytest.fixture
def client():
    run_manager = RunManager()
    app = create_app(run_manager)
    app.config["TESTING"] = True
    yield app.test_client()
    run_manager.stop()


class TestRestValue:
    def test_initial_value_is_null(self, client):
        r = client.get("/api/v1/diagnostics/value")
        assert r.status_code == 200
        assert r.get_json() == {"value": None}

    def test_put_then_get_round_trip(self, client):
        r = client.put("/api/v1/diagnostics/value", json={"value": "42.5"})
        assert r.status_code == 200
        assert r.get_json() == {"value": "42.5"}
        r = client.get("/api/v1/diagnostics/value")
        assert r.get_json() == {"value": "42.5"}

    def test_put_missing_value_400(self, client):
        r = client.put("/api/v1/diagnostics/value", json={})
        assert r.status_code == 400

    def test_put_non_string_value_400(self, client):
        r = client.put("/api/v1/diagnostics/value", json={"value": 42})
        assert r.status_code == 400


class TestMqttPublish:
    def test_publish_success(self, client):
        with patch("simengine.api.diagnostics.mqtt_publish.single") as mock_single:
            r = client.post("/api/v1/diagnostics/mqtt-publish", json={
                "broker": "mqtt://mosquitto:1883",
                "topic": "simengine/diagnostics/value",
                "value": "hello",
            })
        assert r.status_code == 200
        assert r.get_json() == {"ok": True}
        mock_single.assert_called_once_with(
            "simengine/diagnostics/value", payload="hello",
            hostname="mosquitto", port=1883)

    def test_bad_broker_url_400(self, client):
        with patch("simengine.api.diagnostics.mqtt_publish.single") as mock_single:
            r = client.post("/api/v1/diagnostics/mqtt-publish", json={
                "broker": "tcp://mosquitto:1883",
                "topic": "simengine/diagnostics/value",
                "value": "hello",
            })
        assert r.status_code == 400
        mock_single.assert_not_called()

    def test_broker_unreachable_502(self, client):
        with patch("simengine.api.diagnostics.mqtt_publish.single",
                   side_effect=ConnectionRefusedError("refused")):
            r = client.post("/api/v1/diagnostics/mqtt-publish", json={
                "broker": "mqtt://mosquitto:1883",
                "topic": "simengine/diagnostics/value",
                "value": "hello",
            })
        assert r.status_code == 502

    def test_missing_fields_400(self, client):
        r = client.post("/api/v1/diagnostics/mqtt-publish",
                         json={"broker": "mqtt://mosquitto:1883"})
        assert r.status_code == 400
