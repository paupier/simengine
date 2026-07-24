# Schema Export (OPC UA / MQTT / SparkplugB) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user export/copy the exact OPC UA address-space tree, MQTT (Part 14 JSON + flat topics), and SparkplugB (metrics/alias/datatype) schema for a saved scenario, with no run active, via `GET /api/v1/schema` and a new "Schema" section in the Comms tab.

**Architecture:** Refactor `publishers/metrics.py` to expose config-only (name, datatype) schema functions alongside the existing live-value functions (single source of truth, no drift). Refactor `publishers/opcua_server.py` to expose a standalone `build_address_space()` that builds the real, unstarted `opcua.Server` address space (verified: no threads/sockets before `.start()`). A new `api/schema.py` walks that address space and derives the MQTT/SparkplugB schemas from the metrics.py schema functions, replicating SparkplugB's exact alias-assignment order. One new REST endpoint and one new Comms-tab UI section expose it.

**Tech Stack:** Python 3.10, Flask, `opcua` (python-opcua, core dep), pytest.

## Global Constraints

- Determinism: same scenario config => byte-identical schema JSON (repo-wide invariant; see CLAUDE.md "Determinism").
- No behavior change to existing publishers — `station_metrics()`/`line_metrics()`/`OPCUAServerPublisher._build()` must keep producing identical output; existing tests (`test_opcua_publisher.py`, `test_sparkplugb.py`, `test_opcua_mqtt_publisher.py`) must pass unchanged.
- No new dependency — `opcua` and `paho-mqtt` are already core deps (`pyproject.toml`); the `sparkplug` (protobuf) extra is NOT required for schema building, only for actually running `SparkplugBPublisher`.
- Follow existing REST error conventions: 400 for bad input, 404 for unknown scenario (see `GET /api/v1/comms` in `rest.py`).
- `pytest.ini`/`pyproject.toml` sets `pythonpath = ["src", "tests"]`; the autouse fixture in `tests/conftest.py` routes the config loader at `tests/fixtures/line_models_test.yaml`.

---

### Task 1: `metrics.py` — config-only metric schema functions

**Files:**
- Modify: `src/simengine/publishers/metrics.py`
- Test: Create `tests/test_metrics_schema.py`

**Interfaces:**
- Produces: `STATION_METRIC_SCHEMA: Tuple[Tuple[str, str], ...]`, `LINE_METRIC_SCHEMA: Tuple[Tuple[str, str], ...]`, `station_metric_schema(pv_names: list[str]) -> list[tuple[str, str]]`, `line_metric_schema(buffer_names: list[str]) -> list[tuple[str, str]]` — all consumed by Tasks 4/5/6.
- `station_metrics(st)` and `line_metrics(snapshot)` keep their exact existing signatures and output (dict, same keys/order/values) — consumed by `opcua_mqtt.py`, `sparkplugb.py`, `opcua_server.py`, `knowledge_graph.py` (unchanged call sites).

- [ ] **Step 1: Write the failing test**

Create `tests/test_metrics_schema.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metrics_schema.py -v`
Expected: FAIL with `ImportError: cannot import name 'station_metric_schema'`

- [ ] **Step 3: Refactor `metrics.py`**

Replace the full contents of `src/simengine/publishers/metrics.py` with:

```python
"""Shared snapshot -> metric mapping for the MQTT publishers.

Metric names are identical across the Part 14 JSON and SparkplugB encodings
(architecture §3.2): differentiation is transport/encoding, never the data
model. Per-station metric names are unprefixed here; the Part 14 payload
prefixes them with "{Station}." while SparkplugB scopes them by device id.

STATION_METRIC_SCHEMA / LINE_METRIC_SCHEMA are the single source of truth for
"what metrics exist, in what order, with what datatype" — station_metrics()/
line_metrics() zip them with live values; station_metric_schema()/
line_metric_schema() (config-only, no live station/snapshot object) derive
the same name/datatype pairs for schema export (api/schema.py).
"""
from typing import Dict, List, Tuple

# SparkplugB datatype names (mapped to proto enum values in sparkplugb.py)
INT32 = "Int32"
FLOAT = "Float"
STRING = "String"
BOOLEAN = "Boolean"

_SEVERITY_ORDER = {"CRITICAL": 3, "HIGH": 2, "WARNING": 1, "INFO": 0}

STATION_METRIC_SCHEMA: Tuple[Tuple[str, str], ...] = (
    ("State", STRING),
    ("Health", INT32),
    ("PartsMade", INT32),
    ("Good", INT32),
    ("Scrap", INT32),
    ("OEE", FLOAT),
    ("Availability", FLOAT),
    ("Performance", FLOAT),
    ("Quality", FLOAT),
    ("ActiveReasonCode", STRING),
)

LINE_METRIC_SCHEMA: Tuple[Tuple[str, str], ...] = (
    ("SimTime", FLOAT),
    ("LineState", STRING),
    ("Throughput", FLOAT),
    ("TotalWIP", INT32),
    ("TotalGood", INT32),
    ("TotalScrap", INT32),
    ("OEE", FLOAT),
)


def top_reason_code(station_snapshot) -> str:
    alarms = station_snapshot.alarms
    if not alarms:
        return ""
    top = max(alarms, key=lambda a: (_SEVERITY_ORDER.get(a.severity, -1),
                                     a.activated_at))
    return top.code


def station_metric_schema(pv_names: List[str]) -> List[Tuple[str, str]]:
    """Static (name, datatype) pairs for one station's metrics — config-only,
    no live station object needed. Order/names match station_metrics() exactly."""
    schema = list(STATION_METRIC_SCHEMA)
    for name in pv_names:
        schema.append((f"PV/{name}", FLOAT))
    return schema


def line_metric_schema(buffer_names: List[str]) -> List[Tuple[str, str]]:
    """Static (name, datatype) pairs for line-level metrics — config-only.
    Order/names match line_metrics() exactly."""
    schema = list(LINE_METRIC_SCHEMA)
    for name in buffer_names:
        schema.append((f"Buffer/{name}/Level", INT32))
    return schema


def station_metrics(st) -> Dict[str, Tuple[object, str]]:
    """Ordered metric map for one station: name -> (value, datatype)."""
    values = {
        "State": st.state,
        "Health": st.health,
        "PartsMade": st.parts_made,
        "Good": st.good,
        "Scrap": st.scrap,
        "OEE": st.oee,
        "Availability": st.availability,
        "Performance": st.performance,
        "Quality": st.quality,
        "ActiveReasonCode": top_reason_code(st),
    }
    metrics = {name: (values[name], dtype) for name, dtype in STATION_METRIC_SCHEMA}
    for pv in st.process_values:
        metrics[f"PV/{pv.name}"] = (pv.value, FLOAT)
    return metrics


def line_metrics(snapshot) -> Dict[str, Tuple[object, str]]:
    """Ordered metric map for line-level (edge node) data."""
    values = {
        "SimTime": snapshot.sim_time,
        "LineState": snapshot.line_state,
        "Throughput": snapshot.throughput,
        "TotalWIP": snapshot.total_wip,
        "TotalGood": snapshot.total_good,
        "TotalScrap": snapshot.total_scrap,
        "OEE": snapshot.oee,
    }
    metrics = {name: (values[name], dtype) for name, dtype in LINE_METRIC_SCHEMA}
    for bname, buf in snapshot.buffers.items():
        metrics[f"Buffer/{bname}/Level"] = (buf.level, INT32)
    return metrics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_metrics_schema.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Regression-check existing publisher tests**

Run: `pytest tests/test_sparkplugb.py tests/test_opcua_mqtt_publisher.py tests/test_knowledge_graph.py -v`
Expected: PASS, unchanged (these import `station_metrics`/`line_metrics` directly and assert on their output)

- [ ] **Step 6: Commit**

```bash
git add src/simengine/publishers/metrics.py tests/test_metrics_schema.py
git commit -m "refactor: extract config-only metric schema functions in metrics.py"
```

---

### Task 2: `opcua_server.py` — standalone `build_address_space()`

**Files:**
- Modify: `src/simengine/publishers/opcua_server.py`
- Test: Modify `tests/test_opcua_publisher.py` (add one new test class; existing tests must keep passing unchanged)

**Interfaces:**
- Consumes: nothing new (existing `opcua_nodes.py` helpers already imported).
- Produces: `build_address_space(config: dict, port: int, run_id: str = "", speed_ratio: float = 1.0) -> tuple[Server, dict, int]` — `(server, opcua_vars, namespace_idx)`. Consumed by `api/schema.py` (Task 3).
- `OPCUAServerPublisher._build(self, snapshot)` keeps its exact existing signature/behavior — it becomes a thin wrapper.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_opcua_publisher.py` (after the existing `get_by_path` function, before `class TestAddressSpace`):

```python
class TestBuildAddressSpaceStandalone:
    """build_address_space() must be usable with no snapshot at all — the
    schema exporter (api/schema.py) calls it this way."""

    def test_builds_without_snapshot(self):
        from simengine.publishers.opcua_server import build_address_space
        server, v, idx = build_address_space(demo_config(), port=48998)
        assert idx == 2
        node = get_by_path(server, "Acme.Plant1.Area01.Line1_Equipment.Identification.RunID")
        assert node.get_value() == ""  # default when no run_id passed

    def test_placeholder_run_id_and_speed_ratio_used_when_given(self):
        from simengine.publishers.opcua_server import build_address_space
        server, v, idx = build_address_space(
            demo_config(), port=48998, run_id="preview", speed_ratio=2.5)
        run_id_node = get_by_path(
            server, "Acme.Plant1.Area01.Line1_Equipment.Identification.RunID")
        assert run_id_node.get_value() == "preview"
        speed_node = get_by_path(
            server,
            "Acme.Plant1.Area01.Line1_Equipment.OperationsState.Controls.SimSpeedRatio")
        assert speed_node.get_value() == 2.5

    def test_matches_publisher_build_output(self):
        """Same config through _build() (via the publisher) and through
        build_address_space() directly must create the same node IDs."""
        from simengine.publishers.opcua_server import build_address_space

        config = demo_config()
        engine = LineEngine(config, "demo", seed=1, run_id="demo_1")
        pub = OPCUAServerPublisher(config, port=48997)
        pub._build(engine.snapshot())
        pub_node_ids = {str(n.nodeid) for n in _all_variable_nodes(pub.server)}

        server2, _, _ = build_address_space(config, port=48996, run_id="demo_1")
        standalone_node_ids = {str(n.nodeid) for n in _all_variable_nodes(server2)}

        assert pub_node_ids == standalone_node_ids


def _all_variable_nodes(server):
    """Recursively collect every Variable node under Objects (skips the
    standard OPC UA 'Server' diagnostics object, namespace 0)."""
    from opcua import ua
    idx = server.get_namespace_index("http://simengine.local/")

    def walk(node):
        if node.get_node_class() == ua.NodeClass.Variable:
            yield node
        for c in node.get_children():
            yield from walk(c)

    out = []
    for top in server.get_objects_node().get_children():
        if top.nodeid.NamespaceIndex == idx:
            out.extend(walk(top))
    return out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_opcua_publisher.py::TestBuildAddressSpaceStandalone -v`
Expected: FAIL with `ImportError: cannot import name 'build_address_space'`

- [ ] **Step 3: Extract `build_address_space()` in `opcua_server.py`**

In `src/simengine/publishers/opcua_server.py`, replace the `_build` method's body (the whole method from `def _build(self, snapshot) -> None:` through the line `wrap_opcua_vars_with_cache(v, pending=self.pending_writes)`) with a module-level function plus a thin wrapper. The new file section (everything between the reference-type patches and `class OPCUAServerPublisher`, plus the method) becomes:

```python
def build_address_space(config: dict, port: int, run_id: str = "",
                        speed_ratio: float = 1.0):
    """Build the ISA-95 OPC UA address space in memory — no .start(), no
    sockets (verified: opcua.Server() spawns no threads until .start()).
    Reusable both by the live publisher and by the schema exporter
    (api/schema.py), which never starts a server.

    Returns (server, opcua_vars, namespace_idx).
    """
    enterprise = config.get("enterprise", "Enterprise")
    site = config.get("site", "Site")
    area = config.get("area", "Area")
    line = config.get("line_name", "Line1")

    server = Server()
    server.set_endpoint(f"opc.tcp://0.0.0.0:{port}/simengine/")
    server.set_server_name("simengine Station Simulation")
    idx = server.register_namespace("http://simengine.local/")

    objects = server.get_objects_node()
    ent_node = objects.add_object(_nid(enterprise, idx), _qn(enterprise, idx))
    site_node = ent_node.add_object(_nid(f"{enterprise}.{site}", idx), _qn(site, idx))
    area_node = site_node.add_object(
        _nid(f"{enterprise}.{site}.{area}", idx), _qn(area, idx))

    prefix = f"{enterprise}.{site}.{area}.{line}_Equipment"
    line_node = area_node.add_object(_nid(prefix, idx), _qn(f"{line}_Equipment", idx))

    v = {}

    # Identification
    id_p = f"{prefix}.Identification"
    id_node = line_node.add_object(_nid(id_p, idx), _qn("Identification", idx))
    id_node.add_variable(_nid(f"{id_p}.EquipmentID", idx), _qn("EquipmentID", idx), line)
    id_node.add_variable(_nid(f"{id_p}.EquipmentClass", idx), _qn("EquipmentClass", idx), "ProductionLine")
    id_node.add_variable(_nid(f"{id_p}.Description", idx), _qn("Description", idx),
                         config.get("description", f"Line {line}"))
    id_node.add_variable(_nid(f"{id_p}.RunID", idx), _qn("RunID", idx), run_id)

    # OperationsState
    os_p = f"{prefix}.OperationsState"
    os_node = line_node.add_object(_nid(os_p, idx), _qn("OperationsState", idx))
    v["system"] = {
        "simtime": os_node.add_variable(_nid(f"{os_p}.SimTime", idx), _qn("SimTime", idx), 0.0),
        "line_state": os_node.add_variable(_nid(f"{os_p}.LineState", idx), _qn("LineState", idx), "RUNNING"),
    }
    ctrl_p = f"{os_p}.Controls"
    ctrl_node = os_node.add_object(_nid(ctrl_p, idx), _qn("Controls", idx))
    ctrl_node.add_variable(_nid(f"{ctrl_p}.SimSpeedRatio", idx),
                           _qn("SimSpeedRatio", idx), speed_ratio)

    # OperationsPerformance
    op_p = f"{prefix}.OperationsPerformance"
    op_node = line_node.add_object(_nid(op_p, idx), _qn("OperationsPerformance", idx))
    v["line_kpis"] = {
        "throughput": op_node.add_variable(_nid(f"{op_p}.Throughput", idx), _qn("Throughput", idx), 0.0),
        "total_wip": op_node.add_variable(_nid(f"{op_p}.TotalWIP", idx), _qn("TotalWIP", idx), 0),
        "total_scrap": op_node.add_variable(_nid(f"{op_p}.TotalScrap", idx), _qn("TotalScrap", idx), 0),
    }

    # Line OEE
    oee_p = f"{prefix}.OEE"
    oee_node = line_node.add_object(_nid(oee_p, idx), _qn("OEE", idx))
    v["line_oee"] = {
        "line_oee": oee_node.add_variable(_nid(f"{oee_p}.OEE", idx), _qn("OEE", idx), 0.0),
        "line_good_parts": oee_node.add_variable(_nid(f"{oee_p}.GoodPartCount", idx), _qn("GoodPartCount", idx), 0),
    }

    # Resources: stations + buffers
    res_p = f"{prefix}.Resources"
    res_node = line_node.add_object(_nid(res_p, idx), _qn("Resources", idx))
    v["stations"] = {}
    for st_cfg in config["stations"]:
        name = st_cfg["name"]
        pv_units = [(pv["name"], pv["unit"]) for pv in st_cfg.get("process_values", [])]
        v["stations"][name] = create_station_node(
            res_node, idx, name,
            enable_health="health" in st_cfg,
            pv_names_units=pv_units,
            node_prefix=f"{res_p}.{name}_Equipment",
        )
        create_station_asset_node(res_node, idx, name,
                                  node_prefix=f"{res_p}.{name}_Asset")

    v["buffers"] = {}
    for b_cfg in config["buffers"]:
        bname = b_cfg["name"]
        v["buffers"][bname] = create_storage_unit_node(
            res_node, idx, f"{bname}_StorageUnit", b_cfg["capacity"],
            node_prefix=f"{res_p}.{bname}_StorageUnit",
        )

    # SupportFunctions (shift nodes only when shifts configured)
    if config.get("shifts", {}).get("schedule"):
        sf_p = f"{prefix}.SupportFunctions"
        sf_node = line_node.add_object(_nid(sf_p, idx), _qn("SupportFunctions", idx))
        v["shift"] = create_shift_management_node(
            sf_node, idx, node_prefix=f"{sf_p}.ShiftManagement")

    # Line asset node
    asset_p = f"{enterprise}.{site}.{area}.{line}_Asset"
    asset_node = area_node.add_object(_nid(asset_p, idx), _qn(f"{line}_Asset", idx))
    aid_p = f"{asset_p}.Identification"
    aid_node = asset_node.add_object(_nid(aid_p, idx), _qn("Identification", idx))
    aid_node.add_variable(_nid(f"{aid_p}.PhysicalAssetID", idx), _qn("PhysicalAssetID", idx), f"{line}_Asset")
    aid_node.add_variable(_nid(f"{aid_p}.AssetClass", idx), _qn("AssetClass", idx), "ProductionLine")

    return server, v, idx


class OPCUAServerPublisher(StatePublisher):
    """ISA-95 OPC UA TCP server fed from LineSnapshot."""

    def __init__(self, config: dict, port: int = 4840):
        self.config = config
        self.port = port
        self.server = None
        self.opcua_vars = {}
        self.pending_writes = []
        self._started = False

    # ----- address space -----

    def _build(self, snapshot) -> None:
        self.server, self.opcua_vars, _ = build_address_space(
            self.config, self.port,
            run_id=snapshot.run_id, speed_ratio=snapshot.speed_ratio,
        )
        wrap_opcua_vars_with_cache(self.opcua_vars, pending=self.pending_writes)
```

Everything below `class OPCUAServerPublisher` from `# ----- publisher lifecycle -----` onward (`on_run_start`, `publish`, `_flush`, `on_run_end`, `close`) stays exactly as it is today — do not touch it.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_opcua_publisher.py -v`
Expected: PASS (all existing tests + 3 new `TestBuildAddressSpaceStandalone` tests)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/publishers/opcua_server.py tests/test_opcua_publisher.py
git commit -m "refactor: extract build_address_space() for standalone address-space construction"
```

---

### Task 3: `api/schema.py` — OPC UA schema builder

**Files:**
- Create: `src/simengine/api/schema.py`
- Test: Create `tests/test_schema.py`

**Interfaces:**
- Consumes: `simengine.publishers.opcua_server.build_address_space` (Task 2).
- Produces: `build_opcua_schema(config: dict, port: int = 4840) -> dict` with shape `{"endpoint": str, "namespace_uri": str, "address_space": {"name": str, "node_class": str, "children": [...]}}`. Consumed by Task 6 (`build_schema`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_schema.py`:

```python
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
        assert oiltemp["data_type"] == "Float"

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'simengine.api.schema'`

- [ ] **Step 3: Create `api/schema.py`**

```python
"""Wire-schema export for OPC UA / MQTT / SparkplugB — the literal address
space / topic / metric structure a given scenario config will publish, with
no engine run and no broker/server connection required. See
docs/superpowers/specs/2026-07-24-schema-export-design.md.
"""
from __future__ import annotations

from opcua import ua

from simengine.publishers.opcua_server import build_address_space

_DATATYPE_NAMES = {
    ua.VariantType.String: "String",
    ua.VariantType.Int32: "Int32",
    ua.VariantType.Int64: "Int64",
    ua.VariantType.UInt32: "UInt32",
    ua.VariantType.UInt64: "UInt64",
    ua.VariantType.Double: "Double",
    ua.VariantType.Float: "Float",
    ua.VariantType.Boolean: "Boolean",
    ua.VariantType.DateTime: "DateTime",
}


def _walk(node) -> dict:
    node_class = node.get_node_class().name
    entry = {
        "name": node.get_browse_name().Name,
        "node_id": node.nodeid.to_string(),
        "node_class": node_class,
    }
    if node_class == "Variable":
        vtype = node.get_data_type_as_variant_type()
        entry["data_type"] = _DATATYPE_NAMES.get(vtype, str(vtype))
    children = node.get_children()
    if children:
        entry["children"] = [_walk(c) for c in children]
    return entry


def build_opcua_schema(config: dict, port: int = 4840) -> dict:
    """The real ISA-95 address-space tree for `config`, built and walked in
    memory (no `.start()`, no sockets) — same builder functions the live
    OPC UA server publisher uses, so this cannot drift from what a run
    actually serves.
    """
    server, _, idx = build_address_space(config, port, run_id="", speed_ratio=1.0)
    objects = server.get_objects_node()
    own_children = [c for c in objects.get_children()
                    if c.nodeid.NamespaceIndex == idx]
    return {
        "endpoint": f"opc.tcp://<host>:{port}/simengine/",
        "namespace_uri": "http://simengine.local/",
        "address_space": {
            "name": "Objects",
            "node_class": "Object",
            "children": [_walk(c) for c in own_children],
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/schema.py tests/test_schema.py
git commit -m "feat: OPC UA address-space schema export (build_opcua_schema)"
```

---

### Task 4: `api/schema.py` — MQTT (Part 14 + flat topics) schema builder

**Files:**
- Modify: `src/simengine/api/schema.py`
- Test: Modify `tests/test_schema.py`

**Interfaces:**
- Consumes: `simengine.publishers.metrics.{station_metric_schema, line_metric_schema}` (Task 1), `simengine.publishers.opcua_mqtt.flat_topic` (existing).
- Produces: `build_mqtt_schema(config: dict, mqtt_cfg: dict) -> dict` with shape `{"part14": {"data_topic", "status_topic", "publish_interval", "envelope": {..., "Payload": {...}}}, "flat_topics": [{"topic", "payload"}]}`. Consumed by Task 6.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_schema.py`:

```python
from unittest.mock import MagicMock

from simengine.api.schema import build_mqtt_schema
from simengine.engine.line import LineEngine
from simengine.publishers.opcua_mqtt import OPCUAMqttPublisher


MQTT_CFG = {"broker": "mqtt://mosquitto:1883", "publisher_id": "simengine-line1"}


class TestBuildMqttSchema:
    def test_topics(self):
        result = build_mqtt_schema(demo_config(), MQTT_CFG)
        assert result["part14"]["data_topic"] == "opcua/simengine-line1/json"
        assert result["part14"]["status_topic"] == "opcua/simengine-line1/status"

    def test_publish_interval_defaults(self):
        result = build_mqtt_schema(demo_config(), {})
        assert result["part14"]["publish_interval"] == 1
        assert result["part14"]["data_topic"] == "opcua/simengine-line1/json"

    def test_envelope_payload_keys_match_real_publisher(self):
        """No-drift check: the schema's Payload keys must match what
        OPCUAMqttPublisher.publish() actually writes for this config."""
        engine = LineEngine(demo_config(), "demo", seed=1, run_id="schema_test")
        pub = OPCUAMqttPublisher(demo_config(), MQTT_CFG)
        pub._client = MagicMock()
        pub._connected = True
        pub.publish(engine.snapshot())
        envelope_call = [c for c in pub._client.publish.call_args_list
                         if c.args[0] == pub.data_topic][0]
        import json
        real_payload_keys = set(json.loads(envelope_call.args[1])["Payload"].keys())

        schema_result = build_mqtt_schema(demo_config(), MQTT_CFG)
        assert set(schema_result["part14"]["envelope"]["Payload"].keys()) == real_payload_keys

    def test_flat_topics_match_flat_topic_helper(self):
        from simengine.publishers.opcua_mqtt import flat_topic
        result = build_mqtt_schema(demo_config(), MQTT_CFG)
        topics = {t["topic"] for t in result["flat_topics"]}
        assert flat_topic("Line1", "Press01", "State") in topics
        assert flat_topic("Line1", "Press01", "PV/OilTemp") in topics

    def test_flat_topic_payload_shape(self):
        result = build_mqtt_schema(demo_config(), MQTT_CFG)
        entry = result["flat_topics"][0]
        assert set(entry["payload"].keys()) == {"value", "sim_time", "run_id"}
        assert entry["payload"]["sim_time"] == "Float"
        assert entry["payload"]["run_id"] == "String"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema.py::TestBuildMqttSchema -v`
Expected: FAIL with `ImportError: cannot import name 'build_mqtt_schema'`

- [ ] **Step 3: Add `build_mqtt_schema` to `api/schema.py`**

Add these imports to the top of `src/simengine/api/schema.py` (alongside the existing `from simengine.publishers.opcua_server import build_address_space`):

```python
from simengine.publishers.metrics import line_metric_schema, station_metric_schema
from simengine.publishers.opcua_mqtt import flat_topic
```

Append to `src/simengine/api/schema.py`:

```python
def build_mqtt_schema(config: dict, mqtt_cfg: dict) -> dict:
    """Part 14 JSON envelope shape + flat-topic list for `config` — derived
    from the same metric name/datatype schema the real publisher uses
    (metrics.py), so the Payload keys cannot drift from what
    OPCUAMqttPublisher.publish() actually writes.
    """
    line = config.get("line_name", "Line1")
    publisher_id = mqtt_cfg.get("publisher_id", "simengine-line1")
    publish_interval = mqtt_cfg.get("publish_interval", 1)
    stations = config.get("stations", [])
    buffers = config.get("buffers", [])

    payload: dict = {}
    for name, dtype in line_metric_schema([b["name"] for b in buffers]):
        payload[f"Line.{name.replace('/', '.')}"] = dtype

    flat_topics = []
    for st_cfg in stations:
        st_name = st_cfg["name"]
        pv_names = [pv["name"] for pv in st_cfg.get("process_values", [])]
        schema = station_metric_schema(pv_names)
        for name, dtype in schema:
            payload[f"{st_name}.{name.replace('/', '.')}"] = dtype
        for name, dtype in schema:
            flat_topics.append({
                "topic": flat_topic(line, st_name, name),
                "payload": {"value": dtype, "sim_time": "Float", "run_id": "String"},
            })

    return {
        "part14": {
            "data_topic": f"opcua/{publisher_id}/json",
            "status_topic": f"opcua/{publisher_id}/status",
            "publish_interval": publish_interval,
            "envelope": {
                "MessageId": "String",
                "MessageType": "String",
                "PublisherId": "String",
                "DataSetWriterId": "Int32",
                "Timestamp": "String",
                "Payload": payload,
            },
        },
        "flat_topics": flat_topics,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (all `TestBuildOpcuaSchema` + `TestBuildMqttSchema` tests)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/schema.py tests/test_schema.py
git commit -m "feat: MQTT (Part 14 + flat topics) schema export (build_mqtt_schema)"
```

---

### Task 5: `api/schema.py` — SparkplugB schema builder

**Files:**
- Modify: `src/simengine/api/schema.py`
- Test: Modify `tests/test_schema.py`

**Interfaces:**
- Consumes: `simengine.publishers.metrics.{station_metric_schema, line_metric_schema}` (Task 1).
- Produces: `build_sparkplugb_schema(config: dict, spb_cfg: dict) -> dict` with shape `{"group_id", "edge_node_id", "nbirth_topic", "ndata_topic", "ndeath_topic", "ncmd_topic", "node_metrics": [{"name","alias","datatype"}], "devices": [{"station","dbirth_topic","ddata_topic","ddeath_topic","metrics":[...]}]}`. Consumed by Task 6.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_schema.py`:

```python
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
        from unittest.mock import MagicMock
        from simengine.engine.line import LineEngine

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema.py::TestBuildSparkplugbSchema -v`
Expected: FAIL with `ImportError: cannot import name 'build_sparkplugb_schema'`

- [ ] **Step 3: Add `build_sparkplugb_schema` to `api/schema.py`**

Append to `src/simengine/api/schema.py`:

```python
def build_sparkplugb_schema(config: dict, spb_cfg: dict) -> dict:
    """SparkplugB NBIRTH/DBIRTH topic + metric/alias/datatype schema for
    `config`. Replicates SparkplugBPublisher._publish_births()'s exact
    registration order — node metrics (line-level) first, then per station
    in config order — so alias numbers match what a real run assigns,
    without touching protobuf or a broker connection.
    """
    area = config.get("area", "Area")
    line = config.get("line_name", "Line1")
    group_id = spb_cfg.get("group_id", area)
    edge_node_id = spb_cfg.get("edge_node_id", line)
    stations = config.get("stations", [])
    buffers = config.get("buffers", [])

    def topic(msg_type, device=None):
        base = f"spBv1.0/{group_id}/{msg_type}/{edge_node_id}"
        return f"{base}/{device}" if device else base

    next_alias = 1
    node_metrics = [
        {"name": "bdSeq", "alias": None, "datatype": "UInt64"},
        {"name": "Node Control/Rebirth", "alias": None, "datatype": "Boolean"},
    ]
    for name, dtype in line_metric_schema([b["name"] for b in buffers]):
        node_metrics.append({"name": name, "alias": next_alias, "datatype": dtype})
        next_alias += 1

    devices = []
    for st_cfg in stations:
        st_name = st_cfg["name"]
        pv_names = [pv["name"] for pv in st_cfg.get("process_values", [])]
        metrics = []
        for name, dtype in station_metric_schema(pv_names):
            metrics.append({"name": name, "alias": next_alias, "datatype": dtype})
            next_alias += 1
        devices.append({
            "station": st_name,
            "dbirth_topic": topic("DBIRTH", st_name),
            "ddata_topic": topic("DDATA", st_name),
            "ddeath_topic": topic("DDEATH", st_name),
            "metrics": metrics,
        })

    return {
        "group_id": group_id,
        "edge_node_id": edge_node_id,
        "nbirth_topic": topic("NBIRTH"),
        "ndata_topic": topic("NDATA"),
        "ndeath_topic": topic("NDEATH"),
        "ncmd_topic": topic("NCMD"),
        "node_metrics": node_metrics,
        "devices": devices,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (all tests in the file so far)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/schema.py tests/test_schema.py
git commit -m "feat: SparkplugB schema export (build_sparkplugb_schema)"
```

---

### Task 6: Combine into `build_schema()` + REST endpoint

**Files:**
- Modify: `src/simengine/api/schema.py`
- Modify: `src/simengine/api/rest.py`
- Test: Modify `tests/test_schema.py`

**Interfaces:**
- Consumes: `build_opcua_schema`, `build_mqtt_schema`, `build_sparkplugb_schema` (Tasks 3-5).
- Produces: `build_schema(config: dict) -> dict` → `{"opcua": {...}, "mqtt": {...}, "sparkplugb": {...}}`, each carrying an `"enabled"` key. REST: `GET /api/v1/schema?scenario=<name>` → same dict plus `"scenario"` key.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_schema.py`:

```python
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
```

Now add REST tests. Create `tests/test_schema_api.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema.py::TestBuildSchema tests/test_schema_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_schema'`, then 404s from the missing route once that import is patched in (route doesn't exist yet)

- [ ] **Step 3: Add `build_schema` to `api/schema.py`**

Append to `src/simengine/api/schema.py`:

```python
def build_schema(config: dict) -> dict:
    """Full schema export for one scenario config: OPC UA address space +
    MQTT (Part 14 + flat) + SparkplugB, each computed regardless of that
    protocol's `enabled` flag (so a protocol's shape can be previewed
    before it's turned on) but carrying that flag for the UI/caller.
    """
    comms = config.get("comms", {}) or {}
    opcua_cfg = comms.get("opcua", {}) or {}
    mqtt_cfg = comms.get("opcua_mqtt", {}) or {}
    spb_cfg = comms.get("sparkplugb", {}) or {}

    opcua_result = build_opcua_schema(config, port=opcua_cfg.get("port", 4840))
    opcua_result["enabled"] = opcua_cfg.get("enabled", True)

    mqtt_result = build_mqtt_schema(config, mqtt_cfg)
    mqtt_result["enabled"] = mqtt_cfg.get("enabled", False)

    spb_result = build_sparkplugb_schema(config, spb_cfg)
    spb_result["enabled"] = spb_cfg.get("enabled", False)

    return {"opcua": opcua_result, "mqtt": mqtt_result, "sparkplugb": spb_result}
```

- [ ] **Step 4: Add the REST endpoint**

In `src/simengine/api/rest.py`, add this import alongside the existing `from simengine.engine.knowledge_graph import build_knowledge_graph` line:

```python
from simengine.api.schema import build_schema
```

Add this route in the `# ----- knowledge graph -----` section of `create_api_blueprint`, right after `preview_kg()` and before `# ----- plugins helper (comms page) -----`:

```python
    # ----- wire schema export -----

    @api.get("/api/v1/schema")
    def get_schema():
        scenario = request.args.get("scenario")
        if not scenario:
            return jsonify({"error": "scenario query parameter required"}), 400
        data, _ = _load_scenarios_file()
        if scenario not in data:
            return jsonify({"error": f"unknown scenario '{scenario}'"}), 404
        config = _plain(data[scenario])
        try:
            result = build_schema(config)
        except (KeyError, TypeError) as exc:
            return jsonify({"error": f"invalid config: {exc}"}), 400
        result["scenario"] = scenario
        return jsonify(result)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_schema.py tests/test_schema_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Full regression check**

Run: `pytest tests/ -v`
Expected: PASS, full suite green (no test outside this feature should have changed behavior)

Run: `flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source`
Expected: no output, exit code 0

- [ ] **Step 7: Commit**

```bash
git add src/simengine/api/schema.py src/simengine/api/rest.py tests/test_schema.py tests/test_schema_api.py
git commit -m "feat: GET /api/v1/schema endpoint combining OPC UA/MQTT/SparkplugB schema export"
```

---

### Task 7: Comms tab UI — Schema section

**Files:**
- Modify: `src/simengine/api/ui/comms.html`

**Interfaces:**
- Consumes: `GET /api/v1/schema?scenario=<name>` (Task 6). Reads the header scenario picker via the page's existing `currentCommsScenario()` helper and `$` DOM helper (both already defined in `base.html`/`comms.html`, same pattern `loadComms()` uses).
- Produces: nothing consumed elsewhere — a leaf UI feature.

- [ ] **Step 1: Add the Schema section markup**

In `src/simengine/api/ui/comms.html`, insert this block right before `{% block scripts %}` (i.e., after the closing `</ul>` of the "Optional packages" section):

```html
  <h2 class="eyebrow" style="margin-top:20px">Wire schema</h2>
  <p class="muted">The exact OPC UA address space / MQTT / SparkplugB
    structure this scenario will publish — no run required.</p>
  <div style="margin-top:10px; display:flex; gap:10px; align-items:center;">
    <button id="schema-view">View schema</button>
    <button id="schema-download" hidden>Download JSON</button>
  </div>
  <div id="schema-panels" style="margin-top:14px"></div>
```

Add this CSS to the existing `{% block styles %}` section (append inside the `<style>` tag, after the `.pill.ok` rule):

```css
  .schema-panel { margin-top: 10px; }
  .schema-panel summary { cursor: pointer; font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.07em; color: var(--ink-2); padding: 6px 0; }
  .schema-panel pre { font-family: var(--mono); font-size: 12px; max-height: 400px;
    overflow: auto; background: #fafafa; border: 1px solid var(--hairline);
    padding: 10px; margin: 6px 0 0 0; }
  .schema-panel .copy-btn { font-size: 11px; margin-top: 4px; }
```

- [ ] **Step 2: Add the JS**

In `src/simengine/api/ui/comms.html`, inside `{% block scripts %}`, add this before the closing `</script>` (after the existing `loadPlugins();` line):

```javascript
  let lastSchema = null;

  function schemaPanel(id, title, data) {
    const json = JSON.stringify(data, null, 2);
    return `
      <details class="schema-panel card" open>
        <summary>${title}</summary>
        <pre id="schema-pre-${id}">${json.replace(/</g, "&lt;")}</pre>
        <button class="copy-btn" data-copy="${id}">Copy</button>
      </details>`;
  }

  async function viewSchema() {
    const scenario = currentCommsScenario();
    if (!scenario) return;
    try {
      lastSchema = await jget("/api/v1/schema?scenario=" + scenario);
      $("schema-panels").innerHTML =
        schemaPanel("opcua", "OPC UA", lastSchema.opcua) +
        schemaPanel("mqtt", "MQTT (Part 14 + flat topics)", lastSchema.mqtt) +
        schemaPanel("spb", "SparkplugB", lastSchema.sparkplugb);
      $("schema-download").hidden = false;
      $("schema-panels").querySelectorAll("[data-copy]").forEach(btn => {
        btn.addEventListener("click", () => {
          navigator.clipboard.writeText(
            $(`schema-pre-${btn.dataset.copy}`).textContent);
        });
      });
    } catch (e) {
      $("schema-panels").innerHTML = `<div class="msg err">${e.message}</div>`;
    }
  }

  $("schema-view").onclick = viewSchema;
  $("schema-download").onclick = () => {
    if (!lastSchema) return;
    const blob = new Blob([JSON.stringify(lastSchema, null, 2)],
                          {type: "application/json"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${lastSchema.scenario || "schema"}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
```

- [ ] **Step 3: Manual verification**

Run: `python -m simengine --scenario demo_line`
Then open `http://localhost:8080/comms`, select a scenario in the header picker, click "View schema". Confirm:
- Three `<details>` panels render with formatted JSON (OPC UA / MQTT / SparkplugB).
- "Copy" on each panel puts that section's JSON on the clipboard (paste into a text editor to confirm).
- "Download JSON" saves a `<scenario>.json` file containing all three sections plus `"scenario"`.
- Switching the scenario picker and clicking "View schema" again updates all three panels.

Stop the server (Ctrl-C) once confirmed.

- [ ] **Step 4: Commit**

```bash
git add src/simengine/api/ui/comms.html
git commit -m "feat: Schema section in Comms tab (view/copy/download OPC UA/MQTT/SparkplugB schema)"
```

---

## Self-Review Notes

- **Spec coverage:** endpoint (Task 6), OPC UA/MQTT/SparkplugB builders (Tasks 3-5), metrics.py single-source-of-truth refactor (Task 1), `build_address_space` extraction (Task 2), UI section with copy+download (Task 7) — all spec sections covered. No draft/preview-from-unsaved-config endpoint was added, matching the spec's non-goals.
- **No placeholders:** every step has complete, runnable code.
- **Type consistency:** `build_opcua_schema`/`build_mqtt_schema`/`build_sparkplugb_schema` signatures introduced in Tasks 3-5 are used unchanged by `build_schema` in Task 6; `station_metric_schema`/`line_metric_schema` from Task 1 are used unchanged in Tasks 4-5.
