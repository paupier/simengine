"""Tests for the Flask Web UI (docker/webui/app.py).

Focuses on the graph tab routes and API endpoints added for Neo4j integration.
"""
import os
import sys
import pytest

# docker/webui/ is not on the default pythonpath (src tests), so add it here.
_WEBUI_DIR = os.path.join(os.path.dirname(__file__), "..", "docker", "webui")
if _WEBUI_DIR not in sys.path:
    sys.path.insert(0, _WEBUI_DIR)

import app as flask_app_module


@pytest.fixture
def client():
    """Flask test client with TESTING mode enabled."""
    flask_app_module.app.config["TESTING"] = True
    with flask_app_module.app.test_client() as c:
        yield c


# ========== Graph Tab Tests ==========

class TestGraphRoute:
    """Tests for the /graph tab and its API endpoints."""

    def test_graph_page_returns_200(self, client):
        resp = client.get("/graph")
        assert resp.status_code == 200
        assert b"vis.js" in resp.data or b"graph" in resp.data.lower()

    def test_graph_page_has_three_panels(self, client):
        resp = client.get("/graph")
        html = resp.data.decode()
        assert "causal" in html.lower()
        assert "topology" in html.lower()
        assert "compare" in html.lower()


class TestGraphApiCausal:
    def test_causal_no_run_id_returns_400(self, client):
        resp = client.get("/api/graph/causal")
        assert resp.status_code == 400

    def test_causal_returns_nodes_edges(self, client, monkeypatch):
        monkeypatch.setattr("app._query_neo4j_causal", lambda run_id: {
            "nodes": [{"id": "1", "label": "M1", "color": "green"}],
            "edges": [{"from": "1", "to": "2"}],
        })
        resp = client.get("/api/graph/causal?run_id=test_run")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "nodes" in data
        assert "edges" in data

    def test_causal_neo4j_unavailable_returns_503(self, client, monkeypatch):
        monkeypatch.setattr("app._query_neo4j_causal", lambda run_id: (_ for _ in ()).throw(Exception("down")))
        resp = client.get("/api/graph/causal?run_id=test_run")
        assert resp.status_code == 503


class TestGraphApiTopology:
    def test_topology_no_run_id_returns_400(self, client):
        resp = client.get("/api/graph/topology")
        assert resp.status_code == 400

    def test_topology_returns_nodes_edges(self, client, monkeypatch):
        monkeypatch.setattr("app._query_neo4j_topology", lambda run_id: {
            "nodes": [{"id": "M1", "label": "M1", "color": "#2ecc71"}],
            "edges": [{"from": "M1", "to": "B1"}],
        })
        resp = client.get("/api/graph/topology?run_id=test_run")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "nodes" in data


class TestGraphApiCompare:
    def test_compare_missing_run_returns_400(self, client):
        resp = client.get("/api/graph/compare?run_a=a")  # missing run_b
        assert resp.status_code == 400

    def test_compare_returns_two_run_stats(self, client, monkeypatch):
        monkeypatch.setattr("app._query_neo4j_compare", lambda a, b: {
            "run_a": {"total_caused": 12, "avg_depth": 2.1, "top_node": "M2"},
            "run_b": {"total_caused": 8,  "avg_depth": 1.5, "top_node": "M4"},
        })
        resp = client.get("/api/graph/compare?run_a=run_001&run_b=run_002")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "run_a" in data and "run_b" in data


class TestGraphApiNodeEvents:
    def test_node_events_missing_params_returns_400(self, client):
        resp = client.get("/api/graph/node_events?run_id=x")  # missing node
        assert resp.status_code == 400

    def test_node_events_returns_list(self, client, monkeypatch):
        monkeypatch.setattr("app._query_neo4j_node_events", lambda run_id, node: [
            {"sim_time": 10.0, "event_type": "STATE_CHANGE", "old_state": "PROCESSING", "new_state": "FAILED"},
        ])
        resp = client.get("/api/graph/node_events?run_id=test_run&node=M1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_node_events_neo4j_unavailable_returns_503(self, client, monkeypatch):
        monkeypatch.setattr("app._query_neo4j_node_events", lambda run_id, node: (_ for _ in ()).throw(Exception("down")))
        resp = client.get("/api/graph/node_events?run_id=test_run&node=M1")
        assert resp.status_code == 503


class TestNeo4jHistorianToggle:
    def test_scenario_without_historian_has_no_neo4j_checkbox(self, client):
        """Neo4j wrapper is always in the DOM but hidden by default (display:none).
        The ?scenario= param is consumed client-side; the /config route is a static SPA page.
        We verify the wrapper element is present and starts hidden."""
        resp = client.get("/config?scenario=balanced_line")
        assert resp.status_code == 200
        # feat-neo4j-wrapper is always in the HTML, toggled by JS; starts hidden
        assert b"feat-neo4j-wrapper" in resp.data
        assert b'style="display:none;"' in resp.data

    def test_8_machine_scenario_has_neo4j_checkbox(self, client):
        """The config page always contains the feat-neo4j checkbox element (shown/hidden by JS)."""
        resp = client.get("/config?scenario=full_feature_8_machine_line")
        assert resp.status_code == 200
        assert b"feat-neo4j" in resp.data


# ========== --no-csv flag Tests ==========

class TestNoCsvFlag:
    """Tests that _apply_demo_flags suppresses CSV historian in config."""

    def test_apply_demo_flags_disables_csv(self):
        import opcua_server
        config = {
            "historian": {
                "enabled": True,
                "csv": {"enabled": True, "output_dir": "results/historian"},
                "influxdb": {"enabled": False},
            }
        }
        opcua_server._apply_demo_flags(config, no_csv=True)
        assert config["historian"]["csv"]["enabled"] is False
        # InfluxDB unaffected
        assert config["historian"]["influxdb"]["enabled"] is False

    def test_apply_demo_flags_no_csv_false_leaves_csv_enabled(self):
        import opcua_server
        config = {"historian": {"enabled": True, "csv": {"enabled": True}}}
        opcua_server._apply_demo_flags(config, no_csv=False)
        assert config["historian"]["csv"]["enabled"] is True

    def test_apply_demo_flags_no_historian_key_is_safe(self):
        import opcua_server
        config = {}
        opcua_server._apply_demo_flags(config, no_csv=True)  # must not raise
        assert config == {}

    def test_apply_demo_flags_csv_key_absent_is_safe(self):
        import opcua_server
        config = {"historian": {"enabled": True, "influxdb": {"enabled": True}}}
        opcua_server._apply_demo_flags(config, no_csv=True)  # must not raise
        # no csv block, so nothing changes
        assert "csv" not in config["historian"]


import json as _json

# ========== Settings API Tests ==========

class TestSettingsApi:
    """Tests for GET/POST /api/settings."""

    def test_get_settings_returns_defaults(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", tmp_path / "demo_settings.json")
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["demo_mode"] is False
        assert data["retention_days"] == 30

    def test_post_settings_saves_and_returns(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", tmp_path / "demo_settings.json")
        resp = client.post("/api/settings",
                           json={"demo_mode": True, "retention_days": 60},
                           content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["demo_mode"] is True
        assert data["retention_days"] == 60

    def test_post_settings_retention_below_minimum_returns_400(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", tmp_path / "demo_settings.json")
        resp = client.post("/api/settings",
                           json={"demo_mode": False, "retention_days": 3},
                           content_type="application/json")
        assert resp.status_code == 400

    def test_post_settings_retention_above_maximum_returns_400(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", tmp_path / "demo_settings.json")
        resp = client.post("/api/settings",
                           json={"demo_mode": False, "retention_days": 400},
                           content_type="application/json")
        assert resp.status_code == 400

    def test_post_settings_persists_to_file(self, client, tmp_path, monkeypatch):
        path = tmp_path / "demo_settings.json"
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", path)
        client.post("/api/settings",
                    json={"demo_mode": True, "retention_days": 45},
                    content_type="application/json")
        saved = _json.loads(path.read_text())
        assert saved["retention_days"] == 45


# ========== Storage API Tests ==========

class TestStorageApi:
    """Tests for GET /api/settings/storage."""

    def test_storage_returns_structure(self, client, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_influx_storage_info",
                            lambda: {"size_mb": 100.0, "daily_mb": 3.3, "days_of_data": 30})
        monkeypatch.setattr(flask_app_module, "_neo4j_storage_info",
                            lambda: {"size_mb": 20.0, "daily_mb": 0.7, "days_of_data": 30})
        resp = client.get("/api/settings/storage")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "influx" in data
        assert "neo4j" in data
        assert "total_mb" in data
        assert "daily_rate_mb" in data

    def test_storage_totals_correctly(self, client, monkeypatch):
        import pytest
        monkeypatch.setattr(flask_app_module, "_influx_storage_info",
                            lambda: {"size_mb": 100.0, "daily_mb": 10.0, "days_of_data": 30})
        monkeypatch.setattr(flask_app_module, "_neo4j_storage_info",
                            lambda: {"size_mb": 50.0, "daily_mb": 5.0, "days_of_data": 30})
        resp = client.get("/api/settings/storage")
        data = resp.get_json()
        assert data["total_mb"] == pytest.approx(150.0)
        assert data["daily_rate_mb"] == pytest.approx(15.0)

    def test_storage_handles_unavailable_backends(self, client, monkeypatch):
        import pytest
        monkeypatch.setattr(flask_app_module, "_influx_storage_info",
                            lambda: {"size_mb": None, "daily_mb": 16.0, "days_of_data": None})
        monkeypatch.setattr(flask_app_module, "_neo4j_storage_info",
                            lambda: {"size_mb": None, "daily_mb": 1.0, "days_of_data": None})
        resp = client.get("/api/settings/storage")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_mb"] is None
        # daily_rate_mb still has fallback values
        assert data["daily_rate_mb"] == pytest.approx(17.0)
