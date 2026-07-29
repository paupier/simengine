# tests/test_i3x_build.py
import pytest
from simengine.engine.knowledge_graph import build_knowledge_graph
from simengine.api.i3x_build import (
    build_i3x_objects, make_vqt, run_quality, utc_now_iso,
    success_response, error_response, bulk_response, I3X_NAMESPACE_URI,
)


@pytest.fixture
def kg():
    config = {
        "line_name": "Line1", "enterprise": "Acme", "site": "Plant1", "area": "Area01",
        "stations": [
            {"name": "Press01", "cycle_time": 10.0,
             "process_values": [{"name": "OilTemp", "unit": "C", "profile": "constant_noise"}]},
            {"name": "Press02", "cycle_time": 10.0},
        ],
        "buffers": [{"name": "B1", "capacity": 5}],
    }
    return build_knowledge_graph(config, "demo_line")


class TestBuildI3xObjects:
    def test_returns_all_four_lists(self, kg):
        result = build_i3x_objects(kg)
        assert set(result.keys()) == {"objects", "objecttypes", "relationshiptypes", "namespaces"}

    def test_object_count_matches_kg_node_count(self, kg):
        result = build_i3x_objects(kg)
        assert len(result["objects"]) == len(kg.nodes)

    def test_station_object_shape(self, kg):
        result = build_i3x_objects(kg)
        press01 = next(o for o in result["objects"] if o["elementId"] == "station:Press01")
        assert press01["displayName"] == "Press01"
        assert press01["typeElementId"] == "type:Station"
        assert press01["parentId"] == "line:Line1"
        assert press01["isComposition"] is True  # has a HAS_PV edge to its OilTemp PV

    def test_process_value_is_not_a_composition(self, kg):
        result = build_i3x_objects(kg)
        pv = next(o for o in result["objects"] if o["elementId"] == "pv:Press01.OilTemp")
        assert pv["isComposition"] is False

    def test_root_enterprise_object_has_no_parent(self, kg):
        result = build_i3x_objects(kg)
        ent = next(o for o in result["objects"] if o["elementId"] == "enterprise:Acme")
        assert ent["parentId"] is None

    def test_objecttypes_cover_every_kg_node_type(self, kg):
        result = build_i3x_objects(kg)
        node_types = {n["type"] for n in kg.nodes.values()}
        type_ids = {t["elementId"] for t in result["objecttypes"]}
        assert type_ids == {f"type:{t}" for t in node_types}

    def test_relationshiptypes_cover_every_kg_edge_type(self, kg):
        result = build_i3x_objects(kg)
        edge_types = {e["type"] for e in kg.edges}
        rel_ids = {r["elementId"] for r in result["relationshiptypes"]}
        assert rel_ids == {f"rel:{t}" for t in edge_types}

    def test_namespaces_include_i3x_and_the_four_wire_protocols(self, kg):
        result = build_i3x_objects(kg)
        uris = {n["uri"] for n in result["namespaces"]}
        assert I3X_NAMESPACE_URI in uris
        assert {"opcua", "sparkplugb", "mqtt", "rest"} <= {
            u.rsplit("/", 1)[-1] for u in uris if u != I3X_NAMESPACE_URI
        }


class TestVqtHelpers:
    def test_make_vqt_shape(self):
        vqt = make_vqt(42.0, "Good", "2026-01-01T00:00:00.000000Z")
        assert vqt == {"value": 42.0, "quality": "Good", "timestamp": "2026-01-01T00:00:00.000000Z"}

    def test_utc_now_iso_ends_with_z_not_offset(self):
        ts = utc_now_iso()
        assert ts.endswith("Z")
        assert "+00:00" not in ts

    def test_run_quality_running(self):
        class FakeRM:
            state = "RUNNING"
        assert run_quality(FakeRM()) == "Good"

    def test_run_quality_idle(self):
        class FakeRM:
            state = "IDLE"
        assert run_quality(FakeRM()) == "GoodNoData"


class TestResponseWrappers:
    def test_success_response_shape(self):
        assert success_response([1, 2]) == {"success": True, "result": [1, 2]}

    def test_error_response_shape(self):
        assert error_response("not found", 404) == {
            "success": False,
            "responseDetail": {"title": "Not Found", "status": 404, "detail": "not found"},
        }

    def test_bulk_response_all_succeeded(self):
        results = [{"success": True, "elementId": "a", "result": 1}]
        assert bulk_response(results) == {"success": True, "results": results}

    def test_bulk_response_any_failed_is_overall_failure(self):
        results = [
            {"success": True, "elementId": "a", "result": 1},
            {"success": False, "elementId": "b", "responseDetail": {"title": "Not Found", "status": 404, "detail": "x"}},
        ]
        assert bulk_response(results)["success"] is False
