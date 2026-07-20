"""Gate P7.1 — knowledge graph: counts, address binding, determinism."""
import json

import pytest

from simengine.config.loader import load_line_config
from simengine.engine.knowledge_graph import (
    EDGE_TYPES,
    NODE_TYPES,
    STATION_METRIC_NAMES,
    build_knowledge_graph,
)


@pytest.fixture
def demo_kg(monkeypatch):
    monkeypatch.delenv("SIMENGINE_CONFIG_PATH", raising=False)
    config = load_line_config("demo_line")
    return build_knowledge_graph(config, "demo_line"), config


class TestStructure:
    def test_node_counts_demo_line(self, demo_kg):
        kg, config = demo_kg
        assert len(kg.find_nodes("Station")) == 3
        assert len(kg.find_nodes("Buffer")) == 2
        # PVs: Press01 has 3, Weld02 has 1, Pack03 has 0
        assert len(kg.find_nodes("ProcessValue")) == 4
        assert len(kg.find_nodes("FailureMode")) == 1  # bearing_wear
        assert len(kg.find_nodes("CycleStopReason")) == 2  # CS_JAM, CS_NO_PICK
        assert len(kg.find_nodes("Scenario")) == 1
        # metrics: 10 per station
        assert len([n for n in kg.find_nodes("Metric")
                    if n.get("kind") != "spc_monitor"]) == 3 * len(STATION_METRIC_NAMES)

    def test_edge_types_valid(self, demo_kg):
        kg, _ = demo_kg
        assert {e["type"] for e in kg.edges} <= set(EDGE_TYPES)
        assert all(n["type"] in NODE_TYPES for n in kg.nodes.values())

    def test_feeds_chain(self, demo_kg):
        kg, _ = demo_kg
        feeds = kg.find_edges("FEEDS")
        # Press01 -> B1 -> Weld02 -> B2 -> Pack03
        chain = [(e["source"], e["target"]) for e in feeds]
        assert ("station:Press01", "buffer:B1") in chain
        assert ("buffer:B1", "station:Weld02") in chain
        assert ("station:Weld02", "buffer:B2") in chain
        assert ("buffer:B2", "station:Pack03") in chain

    def test_can_raise_codes(self, demo_kg):
        kg, _ = demo_kg
        press_alarms = {n["name"] for n in kg.neighbors("station:Press01", "CAN_RAISE")}
        assert "FM_BEARING_WEAR" in press_alarms
        assert "CS_JAM" in press_alarms
        assert "PV_RAMFORCE_HIGH" in press_alarms
        assert "PV_OILTEMP_HIGH" in press_alarms
        assert "MT_REPAIR" in press_alarms



class TestStationHealthAttrs:
    def test_health_attrs_present_when_configured(self, demo_kg):
        kg, _ = demo_kg
        press = kg.nodes["station:Press01"]
        assert press["health_h_max"] == 5
        assert press["health_cbm_threshold"] == 5  # cbm == h_max -> run-to-failure

        weld = kg.nodes["station:Weld02"]
        assert weld["health_h_max"] == 4
        assert weld["health_cbm_threshold"] == 3  # cbm < h_max -> CBM

    def test_health_attrs_none_when_not_configured(self, demo_kg):
        kg, _ = demo_kg
        pack = kg.nodes["station:Pack03"]
        assert pack["health_h_max"] is None
        assert pack["health_cbm_threshold"] is None


class TestAddressBinding:
    def test_every_pv_has_all_four_addresses(self, demo_kg):
        kg, config = demo_kg
        configured = {(s["name"], pv["name"])
                      for s in config["stations"]
                      for pv in s.get("process_values", [])}
        pv_nodes = kg.find_nodes("ProcessValue")
        assert {(n["station"], n["name"]) for n in pv_nodes} == configured
        for n in pv_nodes:
            addr = n["addresses"]
            assert set(addr.keys()) == {
                "opcua_node_id", "sparkplug_metric", "mqtt_flat_topic", "rest_path"}
            assert addr["opcua_node_id"].startswith("ns=2;s=")
            assert addr["opcua_node_id"].endswith(f".ProcessValues.{n['name']}")
            spb = addr["sparkplug_metric"]
            assert spb["device"] == n["station"]
            assert spb["metric"] == f"PV/{n['name']}"
            assert addr["mqtt_flat_topic"].startswith("simengine/")
            assert f"[name={n['name']}]" in addr["rest_path"]

    def test_opcua_node_id_matches_publisher_address_space(self, demo_kg):
        kg, config = demo_kg
        from simengine.engine.line import LineEngine
        from simengine.publishers.opcua_server import OPCUAServerPublisher
        from opcua import ua

        engine = LineEngine(config, "demo_line", seed=1, run_id="kg_check")
        pub = OPCUAServerPublisher(config, port=48998)
        pub._build(engine.snapshot())
        for n in kg.find_nodes("ProcessValue"):
            path = n["addresses"]["opcua_node_id"].replace("ns=2;s=", "")
            node = pub.server.get_node(ua.NodeId(path, 2))
            assert node.get_value() is not None  # resolvable float

    def test_metric_nodes_have_addresses(self, demo_kg):
        kg, _ = demo_kg
        for n in kg.find_nodes("Metric"):
            if n.get("kind") == "spc_monitor":
                continue
            assert set(n["addresses"].keys()) == {
                "opcua_node_id", "sparkplug_metric", "mqtt_flat_topic", "rest_path"}


class TestDeterminism:
    def test_two_builds_byte_identical(self, monkeypatch):
        monkeypatch.delenv("SIMENGINE_CONFIG_PATH", raising=False)
        blobs = []
        for _ in range(2):
            config = load_line_config("demo_line")
            kg = build_knowledge_graph(config, "demo_line")
            blobs.append(json.dumps(kg.to_node_link()))
        assert blobs[0] == blobs[1]


class TestQueries:
    def test_resolve_semantic_lookup(self, demo_kg):
        kg, _ = demo_kg
        top = kg.resolve("oil temperature on the press")[0]
        assert top["id"] == "pv:Press01.OilTemp"

    def test_filters(self, demo_kg):
        kg, _ = demo_kg
        stations = kg.to_node_link(node_type="Station")
        assert all(n["type"] == "Station" for n in stations["nodes"])
        press = kg.to_node_link(station="Press01")
        assert all(n.get("station") == "Press01" or n.get("name") == "Press01"
                   for n in press["nodes"])

    def test_recipe_node_when_recipe_run(self, monkeypatch):
        monkeypatch.delenv("SIMENGINE_CONFIG_PATH", raising=False)
        config = load_line_config("demo_line")
        kg = build_knowledge_graph(config, "demo_line", recipe_name="quick_test")
        assert kg.find_nodes("Recipe")[0]["name"] == "quick_test"
