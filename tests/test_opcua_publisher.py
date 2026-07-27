"""Gate P4 — OPC UA publisher: address-space shape, PV/reason-code nodes, batching."""
from contextlib import contextmanager

import pytest

from simengine.engine.line import LineEngine
from simengine.publishers.opcua_server import (
    OPCUAServerPublisher,
    build_address_space,
    close_unstarted,
)


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
    """Publisher with a built (unstarted) server — no sockets.

    Still needs close(): asyncua.sync.Server() starts a ThreadLoop in its
    constructor, so an unstarted server holds two non-daemon threads and
    would hang the interpreter at exit.
    """
    config = demo_config()
    engine = LineEngine(config, "demo", seed=1, run_id="demo_1")
    pub = OPCUAServerPublisher(config, port=48999)
    pub._build(engine.snapshot())
    yield pub, engine
    pub.close()


def get_by_path(server, path):
    """Resolve a node by ns=2 string NodeId path."""
    from asyncua import ua
    return server.get_node(ua.NodeId(path, 2))


@contextmanager
def _built(config, port, **kwargs):
    """build_address_space() with guaranteed ThreadLoop teardown."""
    server, v, idx = build_address_space(config, port, **kwargs)
    try:
        yield server, v, idx
    finally:
        close_unstarted(server)


class TestBuildAddressSpaceStandalone:
    """build_address_space() must be usable with no snapshot at all — the
    schema exporter (api/schema.py) calls it this way."""

    def test_builds_without_snapshot(self):
        with _built(demo_config(), 48998) as (server, v, idx):
            assert idx == 2
            node = get_by_path(server, "Line.Identification.RunID")
            assert node.get_value() == ""  # default when no run_id passed

    def test_placeholder_run_id_and_speed_ratio_used_when_given(self):
        with _built(demo_config(), 48998, run_id="preview",
                    speed_ratio=2.5) as (server, v, idx):
            run_id_node = get_by_path(server, "Line.Identification.RunID")
            assert run_id_node.get_value() == "preview"
            speed_node = get_by_path(
                server, "Line.OperationsState.Controls.SimSpeedRatio")
            assert speed_node.get_value() == 2.5

    def test_matches_publisher_build_output(self):
        """Same config through _build() (via the publisher) and through
        build_address_space() directly must create the same node IDs."""
        config = demo_config()
        engine = LineEngine(config, "demo", seed=1, run_id="demo_1")
        pub = OPCUAServerPublisher(config, port=48997)
        pub._build(engine.snapshot())
        try:
            pub_node_ids = {str(n.nodeid) for n in _all_variable_nodes(pub.server)}
        finally:
            pub.close()

        with _built(config, 48996, run_id="demo_1") as (server2, _, _):
            standalone_node_ids = {str(n.nodeid) for n in _all_variable_nodes(server2)}

        assert pub_node_ids == standalone_node_ids


def _all_variable_nodes(server):
    """Recursively collect every Variable node under Objects (skips the
    standard OPC UA 'Server' diagnostics object, namespace 0)."""
    from asyncua import ua
    idx = server.get_namespace_index("http://simengine.local/")

    def walk(node):
        if node.read_node_class() == ua.NodeClass.Variable:
            yield node
        for c in node.get_children():
            yield from walk(c)

    out = []
    for top in server.nodes.objects.get_children():
        if top.nodeid.NamespaceIndex == idx:
            out.extend(walk(top))
    return out


class TestAddressSpace:
    def test_node_id_paths_resolvable(self, publisher):
        pub, _ = publisher
        for path in (
            "Line.Identification.RunID",
            "Line.OperationsState.SimTime",
            "Line.OperationsState.Controls.SimSpeedRatio",
            "Line.OperationsPerformance.Throughput",
            "Line.OEE.OEE",
            "Station.Press01.OperationsState.State",
            "Station.Press01.ProcessValues.OilTemp",
            "Station.Press01.ProcessValues.RamForce",
            "Station.Press01.Alarms.ActiveReasonCode",
            "Station.Press01.Alarms.ActiveReasonText",
            "StationAsset.Press01.Identification.PhysicalAssetID",
            "Buffer.B1.CurrentLevel",
            "LineAsset.Identification.PhysicalAssetID",
        ):
            node = get_by_path(pub.server, path)
            node.get_value()  # raises BadNodeIdUnknown if the id is wrong

    def test_node_ids_survive_isa95_renames(self, publisher):
        """The whole point of the scheme: renaming enterprise/site/area/line
        must not change a single NodeId, only BrowseNames."""
        pub, _ = publisher
        original = {str(n.nodeid) for n in _all_variable_nodes(pub.server)}

        renamed = demo_config()
        renamed.update(enterprise="Globex", site="Plant9",
                       area="Area77", line_name="LineZ")
        with _built(renamed, 48995) as (server2, _, _):
            after = {str(n.nodeid) for n in _all_variable_nodes(server2)}

        assert original == after

    def test_browse_names_still_carry_isa95(self, publisher):
        """NodeIds dropped the ISA-95 path; the browse hierarchy did not."""
        pub, _ = publisher
        node = get_by_path(pub.server, "Line")
        assert node.read_browse_name().Name == "Line1_Equipment"
        area = get_by_path(pub.server, "Area")
        assert area.read_browse_name().Name == "Area01"
        station = get_by_path(pub.server, "Station.Press01")
        assert station.read_browse_name().Name == "Press01_Equipment"

    def test_process_values_are_analog_items_with_units(self, publisher):
        """Optix/UaExpert read engineering units and default trend scaling
        from these properties; a unit in the Description is not
        machine-readable."""
        from asyncua import ua

        pub, _ = publisher
        pv = get_by_path(pub.server, "Station.Press01.ProcessValues.OilTemp")
        assert pv.read_type_definition().Identifier == ua.ObjectIds.AnalogItemType

        props = {p.read_browse_name().Name: p.read_value()
                 for p in pv.get_properties()}
        assert props["EngineeringUnits"].DisplayName.Text == "degC"
        eu_range = props["EURange"]
        assert (eu_range.Low, eu_range.High) == (20.0, 68.0)  # initial..alarm_high

    def test_pv_without_derivable_range_stays_plain(self):
        """No invented scale: EURange is mandatory on AnalogItemType, so a PV
        with nothing to derive from stays a plain variable."""
        from asyncua import ua

        config = demo_config()
        config["stations"][0]["process_values"] = [
            {"name": "Fixed", "unit": "x", "profile": "constant_noise", "mean": 0.0},
        ]
        with _built(config, 48994) as (server, _, _):
            node = get_by_path(server, "Station.Press01.ProcessValues.Fixed")
            assert node.read_type_definition().Identifier == \
                ua.ObjectIds.BaseDataVariableType
            assert node.get_properties() == []

    def test_run_id_value(self, publisher):
        pub, _ = publisher
        node = get_by_path(pub.server, "Line.Identification.RunID")
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
            "Station.Press01.OperationsState.State")
        assert state_node.get_value() in (
            "PROCESSING", "IDLE", "DEGRADED", "STARVED", "BLOCKED")
        sim_node = get_by_path(
            pub.server, "Line.OperationsState.SimTime")
        assert sim_node.get_value() == engine.sim_time

    def test_pv_values_land(self, publisher):
        pub, engine = publisher
        for _ in range(30):
            engine.step()
        snap = engine.snapshot()
        pub.publish(snap)
        node = get_by_path(
            pub.server,
            "Station.Press01.ProcessValues.OilTemp")
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
