"""Wire-schema export (OPC UA / MQTT / SparkplugB) — buildable from a saved
scenario config alone, no run required. See
docs/superpowers/specs/2026-07-24-schema-export-design.md."""
from unittest.mock import MagicMock

from simengine.api.schema import build_opcua_schema
from simengine.engine.line import LineEngine
from simengine.publishers.opcua_mqtt import OPCUAMqttPublisher


def demo_config():
    return {
        "enterprise": "Acme", "site": "Plant1", "area": "Area01",
        "line_name": "Line1",
        "stations": [
            {
                "name": "Press01", "cycle_time": 3.0, "defect_rate": 0.05,
                "health": {"h_max": 3, "p_degrade": 0.01,
                           "mttr": {"distribution": "constant", "value": 10}},
                "process_values": [
                    {"name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
                     "setpoint": 55.0, "tau": 60, "initial": 20.0, "alarm_high": 68},
                ],
            },
            {"name": "Pack02", "cycle_time": 2.0},
        ],
        "buffers": [{"name": "B1", "capacity": 5}],
    }


def _find(tree, name):
    """Depth-first search for a child dict with the given 'name'."""
    if tree.get("name") == name:
        return tree
    for child in tree.get("children", []):
        found = _find(child, name)
        if found is not None:
            return found
    return None


class TestBuildOpcuaSchema:
    def test_top_level_shape(self):
        result = build_opcua_schema(demo_config(), port=4840)
        assert result["endpoint"] == "opc.tcp://<host>:4840/simengine/"
        assert result["namespace_uri"] == "http://simengine.local/"
        assert result["address_space"]["name"] == "Objects"
        assert result["address_space"]["node_class"] == "Object"

    def test_excludes_standard_server_boilerplate_node(self):
        result = build_opcua_schema(demo_config())
        top_names = {c["name"] for c in result["address_space"]["children"]}
        assert "Server" not in top_names

    def test_station_and_pv_nodes_present(self):
        result = build_opcua_schema(demo_config())
        oiltemp = _find(result["address_space"], "OilTemp")
        assert oiltemp is not None
        assert oiltemp["node_class"] == "Variable"
        assert oiltemp["data_type"] == "Double"

    def test_health_nodes_only_for_configured_station(self):
        result = build_opcua_schema(demo_config())
        press_state = _find(result["address_space"], "Press01_Equipment")
        health_state = _find(press_state, "HealthState")
        assert health_state is not None

        pack_state = _find(result["address_space"], "Pack02_Equipment")
        health_state_pack = _find(pack_state, "HealthState")
        assert health_state_pack is None

    def test_deterministic(self):
        r1 = build_opcua_schema(demo_config())
        r2 = build_opcua_schema(demo_config())
        assert r1 == r2


MQTT_CFG = {"broker": "mqtt://mosquitto:1883", "publisher_id": "simengine-line1"}


class TestBuildMqttSchema:
    def test_topics(self):
        from simengine.api.schema import build_mqtt_schema
        result = build_mqtt_schema(demo_config(), MQTT_CFG)
        assert result["part14"]["data_topic"] == "opcua/simengine-line1/json"
        assert result["part14"]["status_topic"] == "opcua/simengine-line1/status"

    def test_publish_interval_defaults(self):
        from simengine.api.schema import build_mqtt_schema
        result = build_mqtt_schema(demo_config(), {})
        assert result["part14"]["publish_interval"] == 1
        assert result["part14"]["data_topic"] == "opcua/simengine-line1/json"

    def test_envelope_payload_keys_match_real_publisher(self):
        """No-drift check: the schema's Payload keys must match what
        OPCUAMqttPublisher.publish() actually writes for this config."""
        from simengine.api.schema import build_mqtt_schema
        engine = LineEngine(demo_config(), "demo", seed=1, run_id="schema_test")
        pub = OPCUAMqttPublisher(demo_config(), MQTT_CFG)
        pub._client = MagicMock()
        pub._connected = True
        pub.publish(engine.snapshot())
        envelope_call = [c for c in pub._client.publish.call_args_list
                         if c.args[0] == pub.data_topic][0]
        import json
        real_payload_keys = list(json.loads(envelope_call.args[1])["Payload"].keys())

        schema_result = build_mqtt_schema(demo_config(), MQTT_CFG)
        schema_keys = list(schema_result["part14"]["envelope"]["Payload"].keys())
        # Order-identical, not merely set-equal, so the schema mirrors the exact
        # live envelope key order (stations first, then line metrics).
        assert schema_keys == real_payload_keys

    def test_flat_topics_match_flat_topic_helper(self):
        from simengine.api.schema import build_mqtt_schema
        from simengine.publishers.opcua_mqtt import flat_topic
        result = build_mqtt_schema(demo_config(), MQTT_CFG)
        topics = {t["topic"] for t in result["flat_topics"]}
        assert flat_topic("Line1", "Press01", "State") in topics
        assert flat_topic("Line1", "Press01", "PV/OilTemp") in topics

    def test_flat_topic_payload_shape(self):
        from simengine.api.schema import build_mqtt_schema
        result = build_mqtt_schema(demo_config(), MQTT_CFG)
        entry = result["flat_topics"][0]
        assert set(entry["payload"].keys()) == {"value", "sim_time", "run_id"}
        assert entry["payload"]["sim_time"] == "Float"
        assert entry["payload"]["run_id"] == "String"

    def test_flat_topics_empty_when_disabled(self):
        from simengine.api.schema import build_mqtt_schema
        result = build_mqtt_schema(demo_config(), {**MQTT_CFG, "flat_topics": False})
        assert result["flat_topics"] == []

    def test_flat_topics_present_by_default(self):
        from simengine.api.schema import build_mqtt_schema
        result = build_mqtt_schema(demo_config(), MQTT_CFG)
        assert len(result["flat_topics"]) > 0


from simengine.api.schema import build_sparkplugb_schema
from simengine.publishers.sparkplugb import SparkplugBPublisher


SPB_CFG = {"broker": "mqtt://localhost:1883", "group_id": "Area01", "edge_node_id": "Line1"}


class TestBuildSparkplugbSchema:
    def test_topics(self):
        result = build_sparkplugb_schema(demo_config(), SPB_CFG)
        assert result["nbirth_topic"] == "spBv1.0/Area01/NBIRTH/Line1"
        assert result["ndata_topic"] == "spBv1.0/Area01/NDATA/Line1"
        assert result["ndeath_topic"] == "spBv1.0/Area01/NDEATH/Line1"
        assert result["ncmd_topic"] == "spBv1.0/Area01/NCMD/Line1"

    def test_group_id_edge_node_id_default_to_area_and_line(self):
        result = build_sparkplugb_schema(demo_config(), {})
        assert result["nbirth_topic"] == "spBv1.0/Area01/NBIRTH/Line1"

    def test_device_topics(self):
        result = build_sparkplugb_schema(demo_config(), SPB_CFG)
        press = [d for d in result["devices"] if d["station"] == "Press01"][0]
        assert press["dbirth_topic"] == "spBv1.0/Area01/DBIRTH/Line1/Press01"
        assert press["ddata_topic"] == "spBv1.0/Area01/DDATA/Line1/Press01"
        assert press["ddeath_topic"] == "spBv1.0/Area01/DDEATH/Line1/Press01"

    def test_node_metrics_include_unaliased_bdseq_and_rebirth(self):
        result = build_sparkplugb_schema(demo_config(), SPB_CFG)
        by_name = {m["name"]: m for m in result["node_metrics"]}
        assert by_name["bdSeq"]["alias"] is None
        assert by_name["bdSeq"]["datatype"] == "UInt64"
        assert by_name["Node Control/Rebirth"]["alias"] is None

    def test_aliases_match_real_publisher_registration_order(self):
        """No-drift check: alias numbers must match what
        SparkplugBPublisher._publish_births() actually assigns for this
        config."""
        engine = LineEngine(demo_config(), "demo", seed=1, run_id="spb_test")
        pub = SparkplugBPublisher(demo_config(), SPB_CFG)
        pub._client = MagicMock()
        pub._connected = True
        pub._publish_births(engine.snapshot())

        schema_result = build_sparkplugb_schema(demo_config(), SPB_CFG)
        schema_node_aliases = {
            m["name"]: m["alias"] for m in schema_result["node_metrics"]
            if m["alias"] is not None
        }
        assert schema_node_aliases == pub._aliases[None]

        for device in schema_result["devices"]:
            schema_device_aliases = {m["name"]: m["alias"] for m in device["metrics"]}
            assert schema_device_aliases == pub._aliases[device["station"]]


from simengine.api.schema import build_schema


class TestBuildSchema:
    def test_combines_all_three_with_enabled_flags(self):
        config = demo_config()
        config["comms"] = {
            "opcua": {"enabled": True, "port": 4840},
            "opcua_mqtt": {"enabled": False},
        }
        result = build_schema(config)
        assert result["opcua"]["enabled"] is True
        assert "address_space" in result["opcua"]
        assert result["mqtt"]["enabled"] is False
        assert "part14" in result["mqtt"]
        assert result["sparkplugb"]["enabled"] is False  # no comms.sparkplugb block

    def test_opcua_defaults_enabled_true_when_no_comms_block(self):
        """Matches build_publishers()'s own default: comms.get("opcua", {"enabled": True})."""
        result = build_schema(demo_config())
        assert result["opcua"]["enabled"] is True

    def test_opcua_enabled_false_when_block_present_without_enabled_key(self):
        """Matches build_publishers()'s real default: the {"enabled": True}
        fallback only applies when the whole comms.opcua key is absent —
        if comms.opcua exists but has no "enabled" key inside it, that's
        disabled, same as build_publishers() would treat it."""
        config = demo_config()
        config["comms"] = {"opcua": {"port": 4840}}
        result = build_schema(config)
        assert result["opcua"]["enabled"] is False
