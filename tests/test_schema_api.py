"""GET /api/v1/schema — REST surface for the wire-schema export (Flask test
client), independent of any active run."""
import pytest

from simengine.api.rest import create_app
from simengine.runtime.run_manager import RunManager


@pytest.fixture
def client():
    run_manager = RunManager()
    app = create_app(run_manager)
    app.config["TESTING"] = True
    yield app.test_client()
    run_manager.stop()


class TestSchemaEndpoint:
    def test_missing_scenario_param_400(self, client):
        r = client.get("/api/v1/schema")
        assert r.status_code == 400

    def test_unknown_scenario_404(self, client):
        r = client.get("/api/v1/schema?scenario=nope")
        assert r.status_code == 404

    def test_known_scenario_returns_all_three_sections(self, client):
        r = client.get("/api/v1/schema?scenario=full_feature_line")
        assert r.status_code == 200
        body = r.get_json()
        assert body["scenario"] == "full_feature_line"
        assert "address_space" in body["opcua"]
        assert "part14" in body["mqtt"]
        assert "devices" in body["sparkplugb"]

    def test_no_run_required(self, client):
        """Confirm this works without ever starting a run — the whole
        point of the feature."""
        assert client.get("/api/v1/runs/current").get_json()["state"] == "IDLE"
        r = client.get("/api/v1/schema?scenario=balanced_line")
        assert r.status_code == 200
