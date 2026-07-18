"""Gate P4 — OPC UA publisher: address-space shape, PV/reason-code nodes, batching."""
import pytest

from simengine.engine.line import LineEngine
from simengine.publishers.opcua_server import OPCUAServerPublisher


def demo_config():
    return {
        "enterprise": "Acme", "site": "Plant1", "area": "Area01",
        "line_name": "Line1",
        "stations": [
            {
                "name": "Press01", "cycle_time": 3.0, "defect_rate": 0.05,
                "health": {"h_max": 3, "p_degrade": 0.01, "cbm_threshold": 3,
                           "mttr": {"distribution": "constant", "value": 10}},
                "process_values": [
                    {"name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
                     "setpoint": 55.0, "tau": 60, "initial": 20.0, "alarm_high": 68},
                    {"name": "RamForce", "unit": "kN", "profile": "cycle_peak",
                     "baseline": 0.0,
                     "peak": {"distribution": "constant", "value": 850}},
                ],
            },
            {"name": "Pack02", "cycle_time": 2.0},
        ],
        "buffers": [{"name": "B1", "capacity": 5}],
    }


@pytest.fixture
def publisher():
    """Publisher with a built (unstarted) server — no sockets."""
    config = demo_config()
    engine = LineEngine(config, "demo", seed=1, run_id="demo_1")
    pub = OPCUAServerPublisher(config, port=48999)
    pub._build(engine.snapshot())
    yield pub, engine
    # never started -> nothing to stop


def get_by_path(server, path):
    """Resolve a node by ns=2 string NodeId path."""
    from opcua import ua
    return server.get_node(ua.NodeId(path, 2))


class TestAddressSpace:
    def test_isa95_hierarchy_paths(self, publisher):
        pub, _ = publisher
        prefix = "Acme.Plant1.Area01.Line1_Equipment"
        for path in (
            f"{prefix}.Identification.RunID",
            f"{prefix}.OperationsState.SimTime",
            f"{prefix}.OperationsState.Controls.SimSpeedRatio",
            f"{prefix}.OperationsPerformance.Throughput",
            f"{prefix}.OEE.OEE",
            f"{prefix}.Resources.Press01_Equipment.OperationsState.State",
            f"{prefix}.Resources.Press01_Equipment.ProcessValues.OilTemp",
            f"{prefix}.Resources.Press01_Equipment.ProcessValues.RamForce",
            f"{prefix}.Resources.Press01_Equipment.Alarms.ActiveReasonCode",
            f"{prefix}.Resources.Press01_Equipment.Alarms.ActiveReasonText",
            f"{prefix}.Resources.Press01_Asset.Identification.PhysicalAssetID",
            f"{prefix}.Resources.B1_StorageUnit.CurrentLevel",
            "Acme.Plant1.Area01.Line1_Asset.Identification.PhysicalAssetID",
        ):
            node = get_by_path(pub.server, path)
            assert node.get_value() is not None or node.get_value() is None  # resolvable

    def test_run_id_value(self, publisher):
        pub, _ = publisher
        node = get_by_path(pub.server,
                           "Acme.Plant1.Area01.Line1_Equipment.Identification.RunID")
        assert node.get_value() == "demo_1"

    def test_health_nodes_only_when_configured(self, publisher):
        pub, _ = publisher
        assert "health" in pub.opcua_vars["stations"]["Press01"]
        assert "health" not in pub.opcua_vars["stations"]["Pack02"]

    def test_no_shift_nodes_without_shifts(self, publisher):
        pub, _ = publisher
        assert "shift" not in pub.opcua_vars


class TestPublishAndBatching:
    def test_publish_writes_values(self, publisher):
        pub, engine = publisher
        for _ in range(10):
            engine.step()
        pub.publish(engine.snapshot())
        state_node = get_by_path(
            pub.server,
            "Acme.Plant1.Area01.Line1_Equipment.Resources.Press01_Equipment"
            ".OperationsState.State")
        assert state_node.get_value() in (
            "PROCESSING", "IDLE", "DEGRADED", "STARVED", "BLOCKED")
        sim_node = get_by_path(
            pub.server, "Acme.Plant1.Area01.Line1_Equipment.OperationsState.SimTime")
        assert sim_node.get_value() == engine.sim_time

    def test_pv_values_land(self, publisher):
        pub, engine = publisher
        for _ in range(30):
            engine.step()
        snap = engine.snapshot()
        pub.publish(snap)
        node = get_by_path(
            pub.server,
            "Acme.Plant1.Area01.Line1_Equipment.Resources.Press01_Equipment"
            ".ProcessValues.OilTemp")
        pv = [p for p in snap.stations["Press01"].process_values
              if p.name == "OilTemp"][0]
        assert node.get_value() == pytest.approx(pv.value)

    def test_batched_write_count_bounded_by_dirty(self, publisher):
        pub, engine = publisher
        engine.step()
        pub.publish(engine.snapshot())  # first publish: everything dirty
        # second publish with no engine step: nothing (or near nothing) changed
        writes = []
        original = pub._flush

        def counting_flush():
            writes.append(len(pub.pending_writes))
            original()

        pub._flush = counting_flush
        pub.publish(engine.snapshot())
        assert writes[0] <= 3  # only floats within dead-band jitter, if any

    def test_pending_cleared_after_flush(self, publisher):
        pub, engine = publisher
        engine.step()
        pub.publish(engine.snapshot())
        assert pub.pending_writes == []
