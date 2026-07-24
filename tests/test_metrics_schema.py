"""Config-only metric schema functions — must match the live station_metrics()/
line_metrics() key order and datatypes exactly (single source of truth, no drift)."""
from simengine.engine.line import LineEngine
from simengine.publishers.metrics import (
    FLOAT,
    STRING,
    line_metric_schema,
    line_metrics,
    station_metric_schema,
    station_metrics,
)


def demo_config():
    return {
        "line_name": "Line1",
        "stations": [
            {"name": "Press01", "cycle_time": 3.0,
             "process_values": [
                 {"name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
                  "setpoint": 55.0, "tau": 60, "initial": 20.0}]},
            {"name": "Pack02", "cycle_time": 2.0},
        ],
        "buffers": [{"name": "B1", "capacity": 5}],
    }


class TestStationMetricSchema:
    def test_matches_live_keys_and_order(self):
        engine = LineEngine(demo_config(), "demo", seed=1, run_id="schema_test")
        live = station_metrics(engine.snapshot().stations["Press01"])
        schema = station_metric_schema(["OilTemp"])
        assert [name for name, _ in schema] == list(live.keys())

    def test_matches_live_datatypes(self):
        engine = LineEngine(demo_config(), "demo", seed=1, run_id="schema_test")
        live = station_metrics(engine.snapshot().stations["Press01"])
        schema = station_metric_schema(["OilTemp"])
        for name, dtype in schema:
            assert dtype == live[name][1]

    def test_no_pvs_omits_pv_entries(self):
        schema = station_metric_schema([])
        assert schema[-1] == ("ActiveReasonCode", STRING)
        assert len(schema) == 10

    def test_pv_entries_appended_as_float(self):
        schema = station_metric_schema(["OilTemp", "RamForce"])
        assert schema[-2:] == [("PV/OilTemp", FLOAT), ("PV/RamForce", FLOAT)]


class TestLineMetricSchema:
    def test_matches_live_keys_and_order(self):
        engine = LineEngine(demo_config(), "demo", seed=1, run_id="schema_test")
        live = line_metrics(engine.snapshot())
        schema = line_metric_schema(["B1"])
        assert [name for name, _ in schema] == list(live.keys())

    def test_no_buffers_omits_buffer_entries(self):
        schema = line_metric_schema([])
        assert schema[-1] == ("OEE", FLOAT)
        assert len(schema) == 7
