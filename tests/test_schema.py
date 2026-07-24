"""Wire-schema export (OPC UA / MQTT / SparkplugB) — buildable from a saved
scenario config alone, no run required. See
docs/superpowers/specs/2026-07-24-schema-export-design.md."""
from simengine.api.schema import build_opcua_schema


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
