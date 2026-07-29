# i3X Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read + subscriptions i3X (CESMII) interface to simengine, positioned as a test/reference data source for i3X tooling — not a production path Optix will consume.

**Architecture:** A new Flask blueprint (`api/i3x.py`) mounted at `/i3x/v1` in the existing `:8080` Flask app, backed by a precomputed object/relationship graph (`api/i3x_build.py`, built once per run alongside the existing `KnowledgeGraph`) and an in-memory subscription registry (`api/i3x_subscriptions.py`, a background thread polling `run_manager.latest_snapshot.step_count` for new data — no engine/run_manager loop changes). Enabled per-scenario via `comms.i3x.enabled`.

**Tech Stack:** Flask (existing), stdlib only (`threading`, `queue`, `uuid`, `time`) — no new dependency.

## Global Constraints

- Spec pin: i3X tag `1.0.0`, commit `34b766442f6ef614d47fe905459a2ea8b91c6f8b` (`cesmii/i3X`). Response/request shapes below are copied from that commit's `demo/server/models.py` and `demo/server/routers/*.py` — do not improvise field names.
- No writes. `PUT /objects/{id}/value|history` routes are never registered.
- No auth — same trusted-network posture as `:8080`/`:8765`.
- `comms.i3x.enabled` gates every route except `/info` (health-check convention, per the reference server's own docstring: "does not require authentication... may be used as a health check").
- `success_response`/`error_response`/`bulk_response` shapes (see Task 3) must be used verbatim for every route — this is the wire contract a real i3X client parses.
- Every new file gets a matching test file in the same task. Run `pytest tests/ -v` and `flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source` at the end of every task.

---

### Task 1: Expose the active run's config on `RunManager`

**Files:**
- Modify: `src/simengine/runtime/run_manager.py:33` (`__init__`), `:47` (`start`, right after `config = load_line_config(scenario)`)
- Test: `tests/test_run_manager.py` (add to existing file if present, else create)

**Interfaces:**
- Produces: `RunManager.config: Optional[dict]` — the raw validated scenario config for the active/most-recent run. Set once in `start()`, **never cleared** in `_finish()` — matches the existing `self.scenario`/`self.run_id` pattern (both stay populated after a stop so `status()` still reports the last run's identity).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_manager.py
import time
from simengine.runtime.run_manager import RunManager


class TestConfigExposure:
    def test_config_is_none_before_any_run(self):
        rm = RunManager()
        assert rm.config is None

    def test_config_set_on_start_and_survives_stop(self):
        rm = RunManager()
        rm.start(scenario="two_station_minimal", seed=1)
        time.sleep(0.2)
        assert rm.config is not None
        assert rm.config["stations"][0]["name"]  # real validated config, not a stub
        rm.stop()
        assert rm.config is not None  # survives stop, like self.scenario does
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_manager.py::TestConfigExposure -v`
Expected: FAIL with `AttributeError: 'RunManager' object has no attribute 'config'`

- [ ] **Step 3: Write minimal implementation**

In `RunManager.__init__` (after `self.scenario: Optional[str] = None` at line 33):

```python
        self.config: Optional[dict] = None
```

In `RunManager.start()`, right after `config = load_line_config(scenario)  # validates; raises ValueError`:

```python
            self.config = config
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_manager.py::TestConfigExposure -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/simengine/runtime/run_manager.py tests/test_run_manager.py
git commit -m "feat: expose RunManager.config for the i3X enable-gate"
```

---

### Task 2: `comms.i3x` config schema

**Files:**
- Modify: `src/simengine/config/loader.py` (`validate_comms`, ~line 305)
- Test: `tests/test_config_validation.py` (add to existing file if present matching `validate_comms` tests, else create)

**Interfaces:**
- Consumes: nothing new.
- Produces: `comms.i3x.enabled: bool` (default `false`) is now a valid, validated scenario config key. No other `comms.i3x.*` keys exist — i3X needs no broker/port, it rides the existing Flask app.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_validation.py
import pytest
from simengine.config.loader import validate_comms


class TestI3xCommsValidation:
    def test_i3x_enabled_true_is_valid(self):
        validate_comms({"comms": {"i3x": {"enabled": True}}})  # must not raise

    def test_i3x_enabled_false_is_valid(self):
        validate_comms({"comms": {"i3x": {"enabled": False}}})  # must not raise

    def test_i3x_absent_is_valid(self):
        validate_comms({"comms": {}})  # must not raise -- default is disabled

    def test_i3x_enabled_must_be_bool(self):
        with pytest.raises(ValueError, match="comms.i3x.enabled must be a boolean"):
            validate_comms({"comms": {"i3x": {"enabled": "yes"}}})

    def test_i3x_block_must_be_mapping(self):
        with pytest.raises(ValueError, match="comms.i3x must be a mapping"):
            validate_comms({"comms": {"i3x": "on"}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_validation.py::TestI3xCommsValidation -v`
Expected: FAIL — `i3x` block is silently ignored today (not validated), so the "must be a boolean"/"must be a mapping" cases raise nothing and the assertion inside `pytest.raises` fails.

- [ ] **Step 3: Write minimal implementation**

In `validate_comms` (`src/simengine/config/loader.py`), extend the existing per-protocol loop. Current code:

```python
    for proto in ("opcua", "opcua_mqtt", "sparkplugb"):
        block = comms.get(proto)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise ValueError(f"comms.{proto} must be a mapping")
        enabled = block.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError(f"comms.{proto}.enabled must be a boolean")
```

Change the tuple to include `i3x` — the existing generic `enabled`-must-be-bool check already covers it, `i3x` needs no protocol-specific block beyond that:

```python
    for proto in ("opcua", "opcua_mqtt", "sparkplugb", "i3x"):
        block = comms.get(proto)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise ValueError(f"comms.{proto} must be a mapping")
        enabled = block.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError(f"comms.{proto}.enabled must be a boolean")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_validation.py::TestI3xCommsValidation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/simengine/config/loader.py tests/test_config_validation.py
git commit -m "feat: validate comms.i3x.enabled in scenario config"
```

---

### Task 3: `i3x_build.py` — object/type/relationship graph + VQT helpers

**Files:**
- Create: `src/simengine/api/i3x_build.py`
- Test: `tests/test_i3x_build.py`

**Interfaces:**
- Consumes: `KnowledgeGraph` (`simengine.engine.knowledge_graph`) — `.nodes: Dict[str, dict]`, `.edges: List[dict]`, `.find_edges(edge_type=...)`. `LineSnapshot` — read informally via `getattr`/dict access in Task 6, not directly here.
- Produces:
  - `I3X_NAMESPACE_URI = "http://simengine.local/i3x/"`
  - `build_i3x_objects(kg: KnowledgeGraph) -> dict` returning `{"objects": [...], "objecttypes": [...], "relationshiptypes": [...], "namespaces": [...]}` — each list already shaped exactly as the i3X wire format (see below), built once and cached by the caller (Task 5 stores it on `run_manager` or a module-level dict keyed by `run_id` — resolved in Task 5).
  - `make_vqt(value, quality: str, timestamp: str) -> dict` → `{"value": value, "quality": quality, "timestamp": timestamp}`.
  - `run_quality(run_manager) -> str` → `"Good"` if `run_manager.state == "RUNNING"`, else `"GoodNoData"`.
  - `utc_now_iso() -> str` → RFC 3339 UTC with literal `Z` suffix (e.g. `"2026-07-28T16:00:00.123456Z"`), matching the pinned reference server's `utc_now_iso()` (the Implementation Guide forbids the `+00:00` offset form).
  - `success_response(result) -> dict`, `error_response(detail: str, status: int = 500) -> dict`, `bulk_response(results: list) -> dict` — copied verbatim (field names, `_HTTP_TITLES` map) from the pinned `demo/server/routers/utils.py`.

**Object/type mapping (verified against the pinned commit's `ObjectInstanceResponse`/`ObjectTypeResponse`/`RelationshipType`/`Namespace` models):**

- `elementId` ← KG node `id` (e.g. `"station:Press01"`) — already unique and stable.
- `displayName` ← node `name`, falling back to `id` if absent.
- `typeElementId` ← `f"type:{node['type']}"`.
- `parentId` ← the KG node reached via a `CONTAINS` edge whose *target* is this node's id (`None` for the root `Enterprise` node, which has no incoming `CONTAINS`).
- `isComposition` ← `True` if this node is the *source* of any `HAS_PV` edge, else `False` (a `Station` with process values is a composition; a `ProcessValue` leaf is not).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_i3x_build.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'simengine.api.i3x_build'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/simengine/api/i3x_build.py
"""i3X (CESMII) object/relationship graph projection over the KnowledgeGraph.

Pinned against i3X tag 1.0.0, commit 34b766442f6ef614d47fe905459a2ea8b91c6f8b
(cesmii/i3X) -- field names and response-wrapper shapes below are copied from
that commit's demo/server/models.py and demo/server/routers/utils.py, not
improvised. See docs/superpowers/specs/2026-07-28-i3x-interface-design.md.

Built once per run alongside KnowledgeGraph (mirrors build_knowledge_graph's
own build-once pattern) -- this is a wire-projection concern, like the OPC
UA/MQTT/SparkplugB projections in publishers/, so it stays out of engine/.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

I3X_NAMESPACE_URI = "http://simengine.local/i3x/"

# Reverse-relationship naming: i3X's RelationshipType.reverseOf requires every
# relationship to declare its inverse's elementId. KG edges are directional
# but the KG itself has no notion of a named inverse, so this repo defines
# one pair of synthetic reverse names per KG edge type.
_REVERSE_OF = {
    "CONTAINS": "CONTAINED_BY", "FEEDS": "FED_BY", "HAS_PV": "PV_OF",
    "HAS_FAILURE_MODE": "FAILURE_MODE_OF", "CAN_RAISE": "RAISED_BY",
    "MEASURED_BY": "MEASURES", "RUNS": "RUN_BY",
}

_HTTP_TITLES = {
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 500: "Internal Server Error", 501: "Not Implemented",
}


def utc_now_iso() -> str:
    """RFC 3339 UTC with a literal 'Z' suffix -- the i3X Implementation Guide
    forbids the '+00:00' offset form."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def make_vqt(value: Any, quality: str, timestamp: str) -> dict:
    return {"value": value, "quality": quality, "timestamp": timestamp}


def run_quality(run_manager) -> str:
    return "Good" if run_manager.state == "RUNNING" else "GoodNoData"


def success_response(result: Any) -> dict:
    return {"success": True, "result": result}


def error_response(detail: str, status: int = 500) -> dict:
    title = _HTTP_TITLES.get(status, "Error")
    return {"success": False, "responseDetail": {"title": title, "status": status, "detail": detail}}


def bulk_response(results: List[dict]) -> dict:
    overall_success = all(r.get("success", False) for r in results)
    return {"success": overall_success, "results": results}


def _parent_id(kg, node_id: str) -> Optional[str]:
    for e in kg.edges:
        if e["type"] == "CONTAINS" and e["target"] == node_id:
            return e["source"]
    return None


def _is_composition(kg, node_id: str) -> bool:
    return any(e["type"] == "HAS_PV" and e["source"] == node_id for e in kg.edges)


def _build_objects(kg) -> List[dict]:
    return [
        {
            "elementId": node_id,
            "displayName": node.get("name", node_id),
            "typeElementId": f"type:{node['type']}",
            "parentId": _parent_id(kg, node_id),
            "isComposition": _is_composition(kg, node_id),
        }
        for node_id, node in kg.nodes.items()
    ]


def _build_objecttypes(kg) -> List[dict]:
    node_types = sorted({n["type"] for n in kg.nodes.values()})
    return [
        {
            "elementId": f"type:{t}",
            "displayName": t,
            "namespaceUri": I3X_NAMESPACE_URI,
            "sourceTypeId": f"simengine.{t}",
            "schema": {"type": "object"},  # KG nodes carry heterogeneous attrs; no fixed schema to declare
        }
        for t in node_types
    ]


def _build_relationshiptypes(kg) -> List[dict]:
    edge_types = sorted({e["type"] for e in kg.edges})
    return [
        {
            "elementId": f"rel:{t}",
            "displayName": t,
            "namespaceUri": I3X_NAMESPACE_URI,
            "relationshipId": f"simengine.{t}",
            "reverseOf": f"rel:{_REVERSE_OF[t]}",
        }
        for t in edge_types
    ]


def _build_namespaces() -> List[dict]:
    return [
        {"uri": I3X_NAMESPACE_URI, "displayName": "simengine i3X"},
        {"uri": "http://simengine.local/opcua", "displayName": "simengine OPC UA"},
        {"uri": "http://simengine.local/sparkplugb", "displayName": "simengine SparkplugB"},
        {"uri": "http://simengine.local/mqtt", "displayName": "simengine MQTT (flat topics)"},
        {"uri": "http://simengine.local/rest", "displayName": "simengine REST"},
    ]


def build_i3x_objects(kg) -> Dict[str, List[dict]]:
    return {
        "objects": _build_objects(kg),
        "objecttypes": _build_objecttypes(kg),
        "relationshiptypes": _build_relationshiptypes(kg),
        "namespaces": _build_namespaces(),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_i3x_build.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/i3x_build.py tests/test_i3x_build.py
git commit -m "feat: i3X object/type/relationship graph builder + VQT helpers"
```

---

### Task 4: `i3x_subscriptions.py` — subscription registry

**Files:**
- Create: `src/simengine/api/i3x_subscriptions.py`
- Test: `tests/test_i3x_subscriptions.py`

**Interfaces:**
- Consumes: `i3x_build.make_vqt`, `i3x_build.utc_now_iso` (Task 3).
- Produces: `SubscriptionRegistry` class, framework-independent (no Flask import), so it's directly unit-testable:
  - `create(client_id: str, display_name: Optional[str] = None) -> dict` → `{"clientId", "subscriptionId", "displayName"}`
  - `register(client_id: str, subscription_id: str, element_ids: List[str], known_element_ids: set) -> List[dict]` → per-element bulk-result dicts (`{"success", "elementId", "result": None}` or `{"success": False, "elementId", "responseDetail"}`)
  - `unregister(client_id, subscription_id, element_ids) -> List[dict]` — same shape
  - `stage_update(element_id: str, value: Any, quality: str, timestamp: str) -> None` — appends to every subscription currently monitoring `element_id`
  - `sync(client_id, subscription_id, last_sequence_number: Optional[int]) -> Optional[List[dict]]` → list of `{"sequenceNumber", "updates"}` batches, or `None` if the subscription doesn't exist
  - `delete(client_id, subscription_ids: List[str]) -> List[dict]`
  - `list(client_id, subscription_ids: List[str]) -> List[dict]`
  - `find(client_id, subscription_id) -> Optional[dict]` — used by Task 8's SSE route

Simplified vs. the pinned reference on purpose (documented, not accidental): no TTL auto-expiry and no queue-overflow/dropped-count tracking. This is a single-operator test/reference server, not a multi-tenant production one — those two features exist there to bound resource usage under sustained load from many clients, which doesn't apply here. Sequence numbering and ack semantics (the actual wire contract a client depends on) are implemented faithfully.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_i3x_subscriptions.py
from simengine.api.i3x_subscriptions import SubscriptionRegistry


class TestCreate:
    def test_create_returns_clientid_subscriptionid_displayname(self):
        reg = SubscriptionRegistry()
        result = reg.create("client-1", "my sub")
        assert result["clientId"] == "client-1"
        assert result["displayName"] == "my sub"
        assert isinstance(result["subscriptionId"], str) and result["subscriptionId"]

    def test_two_creates_get_different_ids(self):
        reg = SubscriptionRegistry()
        a = reg.create("client-1")
        b = reg.create("client-1")
        assert a["subscriptionId"] != b["subscriptionId"]


class TestRegisterUnregister:
    def test_register_known_elements_succeeds(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        results = reg.register("client-1", sub["subscriptionId"], ["a", "b"], known_element_ids={"a", "b"})
        assert all(r["success"] for r in results)

    def test_register_unknown_element_fails_with_404_shape(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        results = reg.register("client-1", sub["subscriptionId"], ["ghost"], known_element_ids={"a"})
        assert results[0]["success"] is False
        assert results[0]["responseDetail"]["status"] == 404

    def test_register_on_missing_subscription_returns_none(self):
        reg = SubscriptionRegistry()
        assert reg.register("client-1", "no-such-sub", ["a"], known_element_ids={"a"}) is None

    def test_register_scoped_to_owning_client(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        # client-2 doesn't own this subscription -- treated as not found
        assert reg.register("client-2", sub["subscriptionId"], ["a"], known_element_ids={"a"}) is None

    def test_unregister_removes_monitoring(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        reg.stage_update("a", 1.0, "Good", "2026-01-01T00:00:00.000000Z")
        reg.unregister("client-1", sub["subscriptionId"], ["a"])
        reg.stage_update("a", 2.0, "Good", "2026-01-01T00:00:01.000000Z")
        batches = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        all_updates = [u for b in batches for u in b["updates"]]
        assert len(all_updates) == 1  # only the update staged before unregister
        assert all_updates[0]["value"] == 1.0


class TestStageAndSync:
    def test_sync_bundles_staged_updates_into_a_batch(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        reg.stage_update("a", 42.0, "Good", "2026-01-01T00:00:00.000000Z")

        batches = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        assert len(batches) == 1
        assert batches[0]["sequenceNumber"] == 1
        assert batches[0]["updates"] == [
            {"elementId": "a", "value": 42.0, "quality": "Good", "timestamp": "2026-01-01T00:00:00.000000Z"}
        ]

    def test_sync_returns_no_new_batch_when_nothing_staged(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        first = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        assert first == []

    def test_ack_removes_acknowledged_batches(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        reg.stage_update("a", 1.0, "Good", "t1")
        b1 = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        assert b1[0]["sequenceNumber"] == 1

        reg.stage_update("a", 2.0, "Good", "t2")
        # Ack sequence 1 -- server must drop it and only return the new batch
        b2 = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=1)
        assert [b["sequenceNumber"] for b in b2] == [2]

    def test_ack_sentinel_minus_one_acks_everything(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        reg.stage_update("a", 1.0, "Good", "t1")
        reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        reg.stage_update("a", 2.0, "Good", "t2")
        reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)

        result = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=-1)
        assert result == []

    def test_sync_on_missing_subscription_returns_none(self):
        reg = SubscriptionRegistry()
        assert reg.sync("client-1", "no-such-sub", last_sequence_number=None) is None


class TestDeleteAndList:
    def test_delete_existing_subscription(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        results = reg.delete("client-1", [sub["subscriptionId"]])
        assert results[0]["success"] is True
        assert reg.find("client-1", sub["subscriptionId"]) is None

    def test_delete_unknown_subscription_fails_with_404_shape(self):
        reg = SubscriptionRegistry()
        results = reg.delete("client-1", ["ghost"])
        assert results[0]["success"] is False
        assert results[0]["responseDetail"]["status"] == 404

    def test_list_returns_monitored_objects(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1", "my sub")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        results = reg.list("client-1", [sub["subscriptionId"]])
        assert results[0]["success"] is True
        assert results[0]["result"]["displayName"] == "my sub"
        assert results[0]["result"]["monitoredObjects"] == [{"elementId": "a"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_i3x_subscriptions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'simengine.api.i3x_subscriptions'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/simengine/api/i3x_subscriptions.py
"""In-memory i3X subscription registry.

Deliberately simpler than the pinned reference server (docs/superpowers/specs/
2026-07-28-i3x-interface-design.md): no TTL auto-expiry, no queue-overflow
tracking. Those exist there to bound resource use under many concurrent
clients over long sessions -- not a concern for a single-operator test/
reference server. Sequence numbering and ack semantics, the actual wire
contract a client depends on, are implemented faithfully.
"""
import threading
import uuid
from typing import Any, Dict, List, Optional

from simengine.api.i3x_build import make_vqt


class _Subscription:
    def __init__(self, client_id: str, subscription_id: str, display_name: Optional[str]):
        self.client_id = client_id
        self.subscription_id = subscription_id
        self.display_name = display_name
        self.monitored_element_ids: set = set()
        self.staged_updates: List[dict] = []
        self.batches: List[dict] = []
        self.next_sequence = 1


class SubscriptionRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs: List[_Subscription] = []

    def _find(self, client_id: str, subscription_id: str) -> Optional[_Subscription]:
        return next(
            (s for s in self._subs if s.subscription_id == subscription_id and s.client_id == client_id),
            None,
        )

    def find(self, client_id: str, subscription_id: str) -> Optional[_Subscription]:
        with self._lock:
            return self._find(client_id, subscription_id)

    def create(self, client_id: str, display_name: Optional[str] = None) -> dict:
        with self._lock:
            sub = _Subscription(client_id, str(uuid.uuid4()), display_name)
            self._subs.append(sub)
            return {"clientId": client_id, "subscriptionId": sub.subscription_id, "displayName": display_name}

    def register(self, client_id: str, subscription_id: str, element_ids: List[str],
                known_element_ids: set) -> Optional[List[dict]]:
        with self._lock:
            sub = self._find(client_id, subscription_id)
            if sub is None:
                return None
            results = []
            for eid in element_ids:
                if eid not in known_element_ids:
                    results.append({"success": False, "elementId": eid,
                                    "responseDetail": {"title": "Not Found", "status": 404,
                                                       "detail": f"Element not found: {eid}"}})
                    continue
                sub.monitored_element_ids.add(eid)
                results.append({"success": True, "elementId": eid, "result": None})
            return results

    def unregister(self, client_id: str, subscription_id: str, element_ids: List[str]) -> Optional[List[dict]]:
        with self._lock:
            sub = self._find(client_id, subscription_id)
            if sub is None:
                return None
            results = []
            for eid in element_ids:
                sub.monitored_element_ids.discard(eid)
                results.append({"success": True, "elementId": eid, "result": None})
            return results

    def stage_update(self, element_id: str, value: Any, quality: str, timestamp: str) -> None:
        with self._lock:
            vqt = make_vqt(value, quality, timestamp)
            for sub in self._subs:
                if element_id in sub.monitored_element_ids:
                    sub.staged_updates.append({"elementId": element_id, **vqt})

    def sync(self, client_id: str, subscription_id: str,
            last_sequence_number: Optional[int]) -> Optional[List[dict]]:
        with self._lock:
            sub = self._find(client_id, subscription_id)
            if sub is None:
                return None

            if last_sequence_number is not None:
                if last_sequence_number == -1:
                    sub.batches.clear()
                else:
                    sub.batches = [b for b in sub.batches if b["sequenceNumber"] > last_sequence_number]

            if sub.staged_updates:
                sub.batches.append({"sequenceNumber": sub.next_sequence, "updates": list(sub.staged_updates)})
                sub.next_sequence += 1
                sub.staged_updates.clear()

            return list(sub.batches)

    def delete(self, client_id: str, subscription_ids: List[str]) -> List[dict]:
        with self._lock:
            results = []
            for sid in subscription_ids:
                sub = self._find(client_id, sid)
                if sub is None:
                    results.append({"success": False, "subscriptionId": sid,
                                    "responseDetail": {"title": "Not Found", "status": 404,
                                                       "detail": f"Subscription not found: {sid}"}})
                    continue
                self._subs.remove(sub)
                results.append({"success": True, "subscriptionId": sid, "result": None})
            return results

    def list(self, client_id: str, subscription_ids: List[str]) -> List[dict]:
        with self._lock:
            results = []
            for sid in subscription_ids:
                sub = self._find(client_id, sid)
                if sub is None:
                    results.append({"success": False, "subscriptionId": sid,
                                    "responseDetail": {"title": "Not Found", "status": 404,
                                                       "detail": f"Subscription not found: {sid}"}})
                    continue
                results.append({"success": True, "subscriptionId": sid, "result": {
                    "subscriptionId": sub.subscription_id,
                    "displayName": sub.display_name,
                    "monitoredObjects": [{"elementId": e} for e in sorted(sub.monitored_element_ids)],
                }})
            return results
```

Note: `register`/`unregister`/`sync` return `None` for a missing subscription — the Flask route layer (Task 7/8) turns that into the actual HTTP 404, keeping this module HTTP-agnostic.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_i3x_subscriptions.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/i3x_subscriptions.py tests/test_i3x_subscriptions.py
git commit -m "feat: i3X in-memory subscription registry"
```

---

### Task 5: Blueprint skeleton — `/info`, `/namespaces`, `/objecttypes`, `/relationshiptypes`

**Files:**
- Create: `src/simengine/api/i3x.py`
- Modify: `src/simengine/api/rest.py:295-327` (`create_app`)
- Test: `tests/test_i3x_api.py`

**Interfaces:**
- Consumes: `i3x_build.build_i3x_objects`, `success_response`, `error_response` (Task 3); `RunManager.config`, `.knowledge_graph`, `.state` (Task 1 + existing).
- Produces: `create_i3x_blueprint(run_manager) -> Blueprint`, registered in `create_app()`. `/info` is always reachable; every other route returns 403 via `error_response` when `comms.i3x.enabled` isn't `true` for the active/most-recent run, or when no run has ever started.

Object graph caching: a module-level `dict` keyed by `run_manager.run_id`, holding the last-built `build_i3x_objects()` result — rebuilt only when `run_id` changes (mirrors `run_manager.knowledge_graph` itself being "built at run start, static per run"). Avoids rebuilding on every request without needing a new `run_manager` attribute for this blueprint's own cache.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_i3x_api.py
import pytest
from simengine.runtime.run_manager import RunManager
from simengine.api.rest import create_app


@pytest.fixture
def client():
    rm = RunManager()
    app = create_app(rm)
    app.testing = True
    return app.test_client(), rm


def _start_with_i3x(client, rm, scenario="two_station_minimal"):
    import time
    resp = client.post("/api/v1/runs", json={"scenario": scenario, "seed": 1})
    assert resp.status_code == 200, resp.get_json()
    time.sleep(0.2)
    rm.config.setdefault("comms", {})["i3x"] = {"enabled": True}


class TestInfoAlwaysReachable:
    def test_info_without_any_run(self, client):
        c, _ = client
        resp = c.get("/i3x/v1/info")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["result"]["specVersion"] == "1.0"

    def test_info_capabilities_shape(self, client):
        c, _ = client
        body = c.get("/i3x/v1/info").get_json()
        caps = body["result"]["capabilities"]
        assert caps == {
            "query": {"history": True},
            "update": {"current": False, "history": False},
            "subscribe": {"stream": True},
        }


class TestEnableGate:
    def test_namespaces_403_when_i3x_not_enabled(self, client):
        c, rm = client
        c.post("/api/v1/runs", json={"scenario": "two_station_minimal", "seed": 1})
        import time; time.sleep(0.2)
        resp = c.get("/i3x/v1/namespaces")
        assert resp.status_code == 403
        assert resp.get_json()["success"] is False

    def test_namespaces_403_when_no_run_ever_started(self, client):
        c, _ = client
        resp = c.get("/i3x/v1/namespaces")
        assert resp.status_code == 403


class TestNamespacesTypesRelationshiptypes:
    def test_namespaces(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.get("/i3x/v1/namespaces")
        assert resp.status_code == 200
        uris = {n["uri"] for n in resp.get_json()["result"]}
        assert "http://simengine.local/i3x/" in uris

    def test_objecttypes(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.get("/i3x/v1/objecttypes")
        assert resp.status_code == 200
        elem_ids = {t["elementId"] for t in resp.get_json()["result"]}
        assert "type:Station" in elem_ids

    def test_objecttypes_query_by_id(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/objecttypes/query", json={"elementIds": ["type:Station", "type:ghost"]})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is False  # one of two failed
        assert body["results"][0]["success"] is True
        assert body["results"][1]["success"] is False
        assert body["results"][1]["responseDetail"]["status"] == 404

    def test_relationshiptypes(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.get("/i3x/v1/relationshiptypes")
        elem_ids = {t["elementId"] for t in resp.get_json()["result"]}
        assert "rel:CONTAINS" in elem_ids

    def test_relationshiptypes_query_by_id(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/relationshiptypes/query", json={"elementIds": ["rel:CONTAINS"]})
        assert resp.get_json()["results"][0]["result"]["reverseOf"] == "rel:CONTAINED_BY"

    def test_object_graph_rebuilds_on_new_run(self, client):
        c, rm = client
        _start_with_i3x(client, rm, scenario="two_station_minimal")
        first_run_id = rm.run_id
        first = {o["elementId"] for o in c.get("/i3x/v1/objecttypes").get_json()["result"]}

        rm.stop()
        import time; time.sleep(0.2)
        _start_with_i3x(client, rm, scenario="demo_line")  # a scenario with different node types (health)
        assert rm.run_id != first_run_id
        second = {o["elementId"] for o in c.get("/i3x/v1/objecttypes").get_json()["result"]}
        # both are valid graphs; the point is the cache actually reflects the new run
        assert second  # non-empty, and no stale exception from a mismatched cache key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_i3x_api.py -v`
Expected: FAIL — `/i3x/v1/info` 404s (route doesn't exist yet)

- [ ] **Step 3: Write minimal implementation**

```python
# src/simengine/api/i3x.py
"""i3X (CESMII) REST interface -- read + subscriptions, no writes.

Positioned as a test/reference data source for i3X tooling, not a production
path Optix will consume. See docs/superpowers/specs/2026-07-28-i3x-interface-
design.md. Pinned against i3X tag 1.0.0.
"""
from flask import Blueprint, jsonify, request

from simengine.api.i3x_build import build_i3x_objects, error_response, success_response

I3X_SPEC_VERSION = "1.0"

# Cache of the last-built object graph, keyed by run_id -- rebuilt only when
# the active run changes, mirroring how run_manager.knowledge_graph itself is
# "built at run start, static per run."
_graph_cache = {"run_id": None, "graph": None}


def _current_graph(run_manager):
    if run_manager.knowledge_graph is None:
        return None
    if _graph_cache["run_id"] != run_manager.run_id:
        _graph_cache["run_id"] = run_manager.run_id
        _graph_cache["graph"] = build_i3x_objects(run_manager.knowledge_graph)
    return _graph_cache["graph"]


def _i3x_enabled(run_manager) -> bool:
    if not run_manager.config:
        return False
    return bool(run_manager.config.get("comms", {}).get("i3x", {}).get("enabled", False))


def create_i3x_blueprint(run_manager) -> Blueprint:
    i3x = Blueprint("i3x", __name__, url_prefix="/i3x/v1")

    @i3x.before_request
    def _gate():
        if request.path == "/i3x/v1/info":
            return None
        if not _i3x_enabled(run_manager):
            return jsonify(error_response(
                "i3X is not enabled for the active scenario (comms.i3x.enabled=false, or no run active)",
                403,
            )), 403
        return None

    @i3x.get("/info")
    def get_info():
        return jsonify(success_response({
            "specVersion": I3X_SPEC_VERSION,
            "serverVersion": None,
            "serverName": "simengine",
            "capabilities": {
                "query": {"history": True},
                "update": {"current": False, "history": False},
                "subscribe": {"stream": True},
            },
        }))

    @i3x.get("/namespaces")
    def get_namespaces():
        graph = _current_graph(run_manager)
        return jsonify(success_response(graph["namespaces"]))

    @i3x.get("/objecttypes")
    def get_objecttypes():
        graph = _current_graph(run_manager)
        return jsonify(success_response(graph["objecttypes"]))

    @i3x.post("/objecttypes/query")
    def query_objecttypes():
        graph = _current_graph(run_manager)
        by_id = {t["elementId"]: t for t in graph["objecttypes"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        for eid in body.get("elementIds", []):
            if eid in by_id:
                results.append({"success": True, "elementId": eid, "result": by_id[eid]})
            else:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Object type not found: {eid}"}})
        overall = all(r["success"] for r in results)
        return jsonify({"success": overall, "results": results})

    @i3x.get("/relationshiptypes")
    def get_relationshiptypes():
        graph = _current_graph(run_manager)
        return jsonify(success_response(graph["relationshiptypes"]))

    @i3x.post("/relationshiptypes/query")
    def query_relationshiptypes():
        graph = _current_graph(run_manager)
        by_id = {t["elementId"]: t for t in graph["relationshiptypes"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        for eid in body.get("elementIds", []):
            if eid in by_id:
                results.append({"success": True, "elementId": eid, "result": by_id[eid]})
            else:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Relationship type not found: {eid}"}})
        overall = all(r["success"] for r in results)
        return jsonify({"success": overall, "results": results})

    return i3x
```

In `src/simengine/api/rest.py`, `create_app()`:

```python
    from simengine.api.chat import create_chat_blueprint
    from simengine.api.i3x import create_i3x_blueprint
    from simengine.api.tools import ToolRegistry

    app = Flask(__name__, template_folder="ui", static_folder="ui/static", static_url_path="/static")
    app.secret_key = secrets.token_hex(32)  # per-process; chat session cookie
    app.register_blueprint(create_api_blueprint(run_manager))
    app.register_blueprint(create_chat_blueprint(ToolRegistry(run_manager)))
    app.register_blueprint(create_i3x_blueprint(run_manager))
```

(Two-line diff: add the import, add the registration call — the surrounding `dashboard`/`configure`/etc. routes are untouched.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_i3x_api.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/i3x.py src/simengine/api/rest.py tests/test_i3x_api.py
git commit -m "feat: i3X blueprint -- info/namespaces/objecttypes/relationshiptypes"
```

---

### Task 6: `/objects`, `/objects/list`, `/objects/related`, `/objects/value`, `/objects/history`

**Files:**
- Modify: `src/simengine/api/i3x.py`
- Test: `tests/test_i3x_api.py` (extend)

**Interfaces:**
- Consumes: `run_manager.latest_snapshot` for live values (existing attribute), `run_quality` (Task 3).
- Produces: five new routes on the same blueprint. Value lookup reads `latest_snapshot` for `Metric`/`ProcessValue` node types by walking the snapshot's `stations[name]` dict using the same field-name maps already declared in `engine/knowledge_graph.py::build_knowledge_graph` (`rest_fields` for metrics, `stations.{name}.process_values[name={pv}].value` path for PVs) -- **do not re-derive these paths**; import and reuse them (see Step 3 for the exact re-export needed).

**Value resolution rule:** an object's VQT `value` is `None` with quality `GoodNoData` when: no run is active, the run is `IDLE`, or the object is a structural node (`Station`, `Line`, ...) with no directly associated live value (only `Metric` and `ProcessValue` nodes resolve to a real value — everything else is a pure structural/composition object, matching `isComposition` semantics from Task 3).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_i3x_api.py

class TestObjects:
    def test_get_objects_returns_full_list(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.get("/i3x/v1/objects")
        assert resp.status_code == 200
        elem_ids = {o["elementId"] for o in resp.get_json()["result"]}
        assert "station:S1" in elem_ids

    def test_objects_list_by_id(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/objects/list", json={"elementIds": ["station:S1", "ghost"]})
        body = resp.get_json()
        assert body["results"][0]["success"] is True
        assert body["results"][1]["success"] is False


class TestObjectsRelated:
    def test_related_returns_neighbors(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/objects/related", json={"elementIds": ["station:S1"]})
        body = resp.get_json()
        assert body["results"][0]["success"] is True
        related = body["results"][0]["result"]
        assert isinstance(related, list) and len(related) > 0
        assert "sourceRelationship" in related[0]
        assert "object" in related[0]


class TestObjectsValue:
    def test_value_for_metric_while_running(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/objects/value", json={"elementIds": ["metric:S1.State"]})
        body = resp.get_json()
        result = body["results"][0]["result"]
        assert result["quality"] == "Good"
        assert result["value"] in ("IDLE", "PROCESSING", "BLOCKED", "STARVED", "DEGRADED", "FAILED", "UNDER_REPAIR")
        assert "timestamp" in result

    def test_value_no_run_is_good_no_data(self, client):
        c, rm = client
        c.post("/api/v1/runs", json={"scenario": "two_station_minimal", "seed": 1})
        import time; time.sleep(0.2)
        rm.config.setdefault("comms", {})["i3x"] = {"enabled": True}
        rm.stop()
        import time; time.sleep(0.2)
        resp = c.post("/i3x/v1/objects/value", json={"elementIds": ["metric:S1.State"]})
        result = resp.get_json()["results"][0]["result"]
        assert result["quality"] == "GoodNoData"

    def test_value_for_unknown_element_404s_in_bulk_result(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/objects/value", json={"elementIds": ["metric:ghost"]})
        result = resp.get_json()["results"][0]
        assert result["success"] is False
        assert result["responseDetail"]["status"] == 404

    def test_value_for_structural_node_is_composition_with_no_value(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/objects/value", json={"elementIds": ["station:S1"]})
        result = resp.get_json()["results"][0]["result"]
        assert result["isComposition"] is True
        assert result["value"] is None
        assert result["quality"] == "GoodNoData"


class TestNoWriteRoutes:
    def test_put_object_value_is_not_registered(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.put("/i3x/v1/objects/value", json={"updates": []})
        assert resp.status_code in (404, 405)  # Flask's default for an unregistered route/method

    def test_put_object_history_is_not_registered(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.put("/i3x/v1/objects/history", json={"updates": []})
        assert resp.status_code in (404, 405)


class TestObjectsHistory:
    def test_history_empty_without_historian(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/objects/history", json={
            "elementIds": ["metric:S1.State"],
            "startTime": "2026-01-01T00:00:00Z", "endTime": "2026-01-02T00:00:00Z",
        })
        result = resp.get_json()["results"][0]["result"]
        assert result["values"] == []
```

(Uses scenario `two_station_minimal`, whose stations are named `S1`/`S2` — confirmed against `config/scenarios.yaml`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_i3x_api.py::TestObjects tests/test_i3x_api.py::TestObjectsRelated tests/test_i3x_api.py::TestObjectsValue tests/test_i3x_api.py::TestObjectsHistory -v`
Expected: FAIL — routes 404

- [ ] **Step 3: Write minimal implementation**

Add to `src/simengine/api/i3x.py`, after the existing `query_relationshiptypes` route and before `return i3x`:

```python
    @i3x.get("/objects")
    def get_objects():
        graph = _current_graph(run_manager)
        return jsonify(success_response(graph["objects"]))

    @i3x.post("/objects/list")
    def list_objects():
        graph = _current_graph(run_manager)
        by_id = {o["elementId"]: o for o in graph["objects"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        for eid in body.get("elementIds", []):
            if eid in by_id:
                results.append({"success": True, "elementId": eid, "result": by_id[eid]})
            else:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Element not found: {eid}"}})
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/objects/related")
    def objects_related():
        kg = run_manager.knowledge_graph
        graph = _current_graph(run_manager)
        by_id = {o["elementId"]: o for o in graph["objects"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        for eid in body.get("elementIds", []):
            if eid not in by_id:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Element not found: {eid}"}})
                continue
            related = []
            for edge in kg.edges:
                if edge["source"] == eid:
                    related.append({"sourceRelationship": f"rel:{edge['type']}", "object": by_id[edge["target"]]})
                elif edge["target"] == eid:
                    related.append({"sourceRelationship": f"rel:{edge['type']}", "object": by_id[edge["source"]]})
            results.append({"success": True, "elementId": eid, "result": related})
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/objects/value")
    def objects_value():
        graph = _current_graph(run_manager)
        by_id = {o["elementId"]: o for o in graph["objects"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        for eid in body.get("elementIds", []):
            obj = by_id.get(eid)
            if obj is None:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Element not found: {eid}"}})
                continue
            value = _resolve_value(run_manager, eid)
            quality = run_quality(run_manager) if value is not None else "GoodNoData"
            timestamp = utc_now_iso()
            results.append({"success": True, "elementId": eid, "result": {
                "isComposition": obj["isComposition"],
                **make_vqt(value, quality, timestamp),
            }})
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/objects/history")
    def objects_history():
        graph = _current_graph(run_manager)
        by_id = {o["elementId"]: o for o in graph["objects"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        for eid in body.get("elementIds", []):
            obj = by_id.get(eid)
            if obj is None:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Element not found: {eid}"}})
                continue
            # No in-process value history by design (see the SPC/Welford memory
            # note in CLAUDE.md) -- empty is the valid, spec-shaped answer, not
            # an error, unless a historian-influx backend is wired in later.
            results.append({"success": True, "elementId": eid, "result": {
                "isComposition": obj["isComposition"], "values": [],
            }})
        return jsonify({"success": all(r["success"] for r in results), "results": results})
```

Add the imports and the `_resolve_value` helper near the top of `i3x.py` (below the existing imports):

```python
from simengine.api.i3x_build import make_vqt, run_quality, utc_now_iso

# {node_type: metric-name -> snapshot field name}, copied from the exact maps
# already used to build each Metric node's REST address in
# engine/knowledge_graph.py::build_knowledge_graph -- do not re-derive these.
_METRIC_REST_FIELDS = {
    "State": "state", "Health": "health", "PartsMade": "parts_made",
    "Good": "good", "Scrap": "scrap", "OEE": "oee",
    "Availability": "availability", "Performance": "performance",
    "Quality": "quality", "ActiveReasonCode": "alarms",
}


def _resolve_value(run_manager, element_id: str):
    """Live value for a Metric or ProcessValue node id; None for anything else
    (structural nodes have no directly associated value -- see Task 6's
    docstring in the plan for the isComposition/value split)."""
    snap = run_manager.latest_snapshot
    if snap is None:
        return None

    if element_id.startswith("metric:"):
        station_name, metric = element_id[len("metric:"):].split(".", 1)
        field = _METRIC_REST_FIELDS.get(metric)
        if field is None:
            return None
        station = next((s for s in snap.stations if s.name == station_name), None)
        if station is None:
            return None
        value = getattr(station, field, None)
        if field == "alarms":
            return value[0].reason_code if value else None
        return value

    if element_id.startswith("pv:"):
        station_name, pv_name = element_id[len("pv:"):].split(".", 1)
        station = next((s for s in snap.stations if s.name == station_name), None)
        if station is None:
            return None
        pv = next((p for p in station.process_values if p.name == pv_name), None)
        return pv.value if pv else None

    return None
```

**Before implementing `_resolve_value`, read `src/simengine/engine/snapshot.py`** to confirm the exact attribute names (`snap.stations`, `station.name`, `station.state`, `station.process_values`, `pv.name`, `pv.value`, and how active alarms are represented — e.g. whether it's `station.alarms` or `station.active_alarms`, and the exact field holding a reason code) — the sketch above uses names inferred from `knowledge_graph.py`'s `rest_fields` map and REST path convention (`stations.{name}.process_values[name={pv}].value`), not a verified read of `snapshot.py` itself. Adjust attribute access to match exactly; this is the one part of this task not independently verified against source during planning.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_i3x_api.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/i3x.py tests/test_i3x_api.py
git commit -m "feat: i3X objects/related/value/history routes"
```

---

### Task 7: Subscription CRUD routes

**Files:**
- Modify: `src/simengine/api/i3x.py`
- Test: `tests/test_i3x_api.py` (extend)

**Interfaces:**
- Consumes: `SubscriptionRegistry` (Task 4), instantiated once per blueprint (module-level, like `_graph_cache`).
- Produces: `POST /subscriptions`, `POST /subscriptions/register`, `POST /subscriptions/unregister`, `POST /subscriptions/delete`, `POST /subscriptions/list`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_i3x_api.py

class TestSubscriptionCrud:
    def test_create_then_register_then_list(self, client):
        c, rm = client
        _start_with_i3x(client, rm)

        created = c.post("/i3x/v1/subscriptions",
                         json={"clientId": "test-client", "displayName": "watch S1"}).get_json()
        assert created["success"] is True
        sub_id = created["result"]["subscriptionId"]

        reg = c.post("/i3x/v1/subscriptions/register", json={
            "clientId": "test-client", "subscriptionId": sub_id, "elementIds": ["metric:S1.State"],
        }).get_json()
        assert reg["results"][0]["success"] is True

        listed = c.post("/i3x/v1/subscriptions/list",
                        json={"clientId": "test-client", "subscriptionIds": [sub_id]}).get_json()
        assert listed["results"][0]["result"]["monitoredObjects"] == [{"elementId": "metric:S1.State"}]

    def test_register_unknown_element_404s(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        sub_id = c.post("/i3x/v1/subscriptions", json={"clientId": "c1"}).get_json()["result"]["subscriptionId"]
        resp = c.post("/i3x/v1/subscriptions/register",
                      json={"clientId": "c1", "subscriptionId": sub_id, "elementIds": ["ghost"]})
        assert resp.get_json()["results"][0]["responseDetail"]["status"] == 404

    def test_register_on_missing_subscription_404s(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/subscriptions/register",
                      json={"clientId": "c1", "subscriptionId": "no-such-sub", "elementIds": ["metric:S1.State"]})
        assert resp.status_code == 404

    def test_delete_subscription(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        sub_id = c.post("/i3x/v1/subscriptions", json={"clientId": "c1"}).get_json()["result"]["subscriptionId"]
        resp = c.post("/i3x/v1/subscriptions/delete", json={"clientId": "c1", "subscriptionIds": [sub_id]})
        assert resp.get_json()["results"][0]["success"] is True
        listed = c.post("/i3x/v1/subscriptions/list", json={"clientId": "c1", "subscriptionIds": [sub_id]}).get_json()
        assert listed["results"][0]["success"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_i3x_api.py::TestSubscriptionCrud -v`
Expected: FAIL — routes 404

- [ ] **Step 3: Write minimal implementation**

Add near the top of `i3x.py` (module-level, alongside `_graph_cache`):

```python
from simengine.api.i3x_subscriptions import SubscriptionRegistry

_subscriptions = SubscriptionRegistry()
```

Add routes to `create_i3x_blueprint`, before `return i3x`:

```python
    @i3x.post("/subscriptions")
    def create_subscription():
        body = request.get_json(force=True, silent=True) or {}
        result = _subscriptions.create(body["clientId"], body.get("displayName"))
        return jsonify(success_response(result))

    @i3x.post("/subscriptions/register")
    def register_subscription():
        body = request.get_json(force=True, silent=True) or {}
        graph = _current_graph(run_manager)
        known_ids = {o["elementId"] for o in graph["objects"]}
        results = _subscriptions.register(body["clientId"], body["subscriptionId"],
                                          body.get("elementIds", []), known_ids)
        if results is None:
            return jsonify(error_response("Subscription not found", 404)), 404
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/subscriptions/unregister")
    def unregister_subscription():
        body = request.get_json(force=True, silent=True) or {}
        results = _subscriptions.unregister(body["clientId"], body["subscriptionId"], body.get("elementIds", []))
        if results is None:
            return jsonify(error_response("Subscription not found", 404)), 404
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/subscriptions/delete")
    def delete_subscriptions():
        body = request.get_json(force=True, silent=True) or {}
        results = _subscriptions.delete(body["clientId"], body.get("subscriptionIds", []))
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/subscriptions/list")
    def list_subscriptions():
        body = request.get_json(force=True, silent=True) or {}
        results = _subscriptions.list(body["clientId"], body.get("subscriptionIds", []))
        return jsonify({"success": all(r["success"] for r in results), "results": results})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_i3x_api.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/i3x.py tests/test_i3x_api.py
git commit -m "feat: i3X subscription create/register/unregister/delete/list routes"
```

---

### Task 8: `/subscriptions/stream` (SSE) and `/subscriptions/sync`, wired to the snapshot cadence

**Files:**
- Modify: `src/simengine/api/i3x.py`
- Test: `tests/test_i3x_api.py` (extend)

**Interfaces:**
- Consumes: `SubscriptionRegistry.stage_update`/`.sync`/`.find` (Task 4); reuses the SSE generator/`_sse`-style pattern already established in `chat.py:109` (`_sse(event: dict) -> str`).
- Produces: a background daemon thread, started once at blueprint-creation time, polling `run_manager.latest_snapshot.step_count` every 0.2s; on change, resolves and stages a fresh VQT for every currently-monitored element id across all subscriptions. `POST /subscriptions/stream` (SSE) and `POST /subscriptions/sync` both read from the same staged/batched data via `SubscriptionRegistry`.

Polling, not a step-loop hook, by design: adding an observer callback into `LineEngine`/`RunManager`'s step loop would be an engine-adjacent change this design explicitly avoids ("no engine changes" — see the design doc's Architecture section). A 0.2s poll on `step_count` is simple, fully decoupled, and indistinguishable from true push at the granularity this interface's actual use case (i3X client tooling validation) cares about.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_i3x_api.py
import time


class TestSync:
    def test_sync_receives_updates_after_polling_interval(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        sub_id = c.post("/i3x/v1/subscriptions", json={"clientId": "c1"}).get_json()["result"]["subscriptionId"]
        c.post("/i3x/v1/subscriptions/register",
              json={"clientId": "c1", "subscriptionId": sub_id, "elementIds": ["metric:S1.State"]})

        time.sleep(0.5)  # let the poll worker observe at least one step_count change

        resp = c.post("/i3x/v1/subscriptions/sync",
                      json={"clientId": "c1", "subscriptionId": sub_id, "lastSequenceNumber": None})
        body = resp.get_json()
        assert body["success"] is True
        assert len(body["result"]) >= 1
        assert body["result"][0]["updates"][0]["elementId"] == "metric:S1.State"

    def test_sync_on_missing_subscription_404s(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/subscriptions/sync",
                      json={"clientId": "c1", "subscriptionId": "no-such-sub", "lastSequenceNumber": None})
        assert resp.status_code == 404


class TestStream:
    def test_stream_emits_at_least_one_sse_event(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        sub_id = c.post("/i3x/v1/subscriptions", json={"clientId": "c1"}).get_json()["result"]["subscriptionId"]
        c.post("/i3x/v1/subscriptions/register",
              json={"clientId": "c1", "subscriptionId": sub_id, "elementIds": ["metric:S1.State"]})
        time.sleep(0.5)

        resp = c.post("/i3x/v1/subscriptions/stream", json={"clientId": "c1", "subscriptionId": sub_id})
        assert resp.mimetype == "text/event-stream"
        # Flask's test client buffers the generator eagerly; take the first chunk.
        chunk = next(resp.response)
        assert b"data:" in chunk
        assert b"metric:S1.State" in chunk

    def test_stream_on_missing_subscription_404s(self, client):
        c, rm = client
        _start_with_i3x(client, rm)
        resp = c.post("/i3x/v1/subscriptions/stream", json={"clientId": "c1", "subscriptionId": "no-such-sub"})
        assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_i3x_api.py::TestSync tests/test_i3x_api.py::TestStream -v`
Expected: FAIL — routes 404, no poll worker exists yet

- [ ] **Step 3: Write minimal implementation**

Add near the top of `i3x.py`, after the `_subscriptions = SubscriptionRegistry()` line:

```python
import json
import threading
import time as _time

from flask import Response


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _start_poll_worker(run_manager):
    """Background daemon: every 0.2s, if a new snapshot has arrived, stage a
    fresh VQT for every element id currently monitored by any subscription."""
    last_step_count = {"value": None}

    def _poll():
        while True:
            _time.sleep(0.2)
            snap = run_manager.latest_snapshot
            if snap is None or snap.step_count == last_step_count["value"]:
                continue
            last_step_count["value"] = snap.step_count
            graph = _current_graph(run_manager)
            if graph is None:
                continue
            timestamp = utc_now_iso()
            quality = run_quality(run_manager)
            monitored_ids = _subscriptions.all_monitored_element_ids()
            for eid in monitored_ids:
                value = _resolve_value(run_manager, eid)
                _subscriptions.stage_update(eid, value, quality if value is not None else "GoodNoData", timestamp)

    thread = threading.Thread(target=_poll, daemon=True, name="i3x-subscription-poller")
    thread.start()
```

Add `all_monitored_element_ids()` to `SubscriptionRegistry` (Task 4's file, `src/simengine/api/i3x_subscriptions.py`), inside the class:

```python
    def all_monitored_element_ids(self) -> set:
        with self._lock:
            out = set()
            for sub in self._subs:
                out |= sub.monitored_element_ids
            return out
```

Add its test to `tests/test_i3x_subscriptions.py`:

```python
class TestAllMonitoredElementIds:
    def test_union_across_subscriptions(self):
        reg = SubscriptionRegistry()
        s1 = reg.create("c1")
        s2 = reg.create("c1")
        reg.register("c1", s1["subscriptionId"], ["a"], known_element_ids={"a", "b"})
        reg.register("c1", s2["subscriptionId"], ["b"], known_element_ids={"a", "b"})
        assert reg.all_monitored_element_ids() == {"a", "b"}
```

Add the two routes to `create_i3x_blueprint`, before `return i3x`, and start the poll worker once at the end of `create_i3x_blueprint` (before `return i3x`):

```python
    @i3x.post("/subscriptions/sync")
    def sync_subscription():
        body = request.get_json(force=True, silent=True) or {}
        batches = _subscriptions.sync(body["clientId"], body["subscriptionId"], body.get("lastSequenceNumber"))
        if batches is None:
            return jsonify(error_response("Subscription not found", 404)), 404
        return jsonify(success_response(batches))

    @i3x.post("/subscriptions/stream")
    def stream_subscription():
        body = request.get_json(force=True, silent=True) or {}
        client_id, subscription_id = body["clientId"], body["subscriptionId"]
        if _subscriptions.find(client_id, subscription_id) is None:
            return jsonify(error_response("Subscription not found", 404)), 404

        def _events():
            last_acked = None
            while True:
                batches = _subscriptions.sync(client_id, subscription_id, last_acked)
                if batches is None:
                    return  # subscription deleted mid-stream
                for batch in batches:
                    yield _sse(batch)
                    last_acked = batch["sequenceNumber"]
                _time.sleep(0.25)

        return Response(_events(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    _start_poll_worker(run_manager)

    return i3x
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_i3x_api.py tests/test_i3x_subscriptions.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/i3x.py src/simengine/api/i3x_subscriptions.py tests/test_i3x_api.py tests/test_i3x_subscriptions.py
git commit -m "feat: i3X SSE stream + sync, backed by a snapshot-cadence poll worker"
```

---

### Task 9: Full-suite regression check + flake8

**Files:** none new — verification only.

- [ ] **Step 1:** Run `pytest tests/ -v` — expect all tests (existing + every test added in Tasks 1-8) to pass, including no unexpected interaction between the new poll-worker daemon thread and existing tests (e.g. `test_run_manager.py`'s determinism tests running back-to-back with i3X tests in the same session).
- [ ] **Step 2:** Run `flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source` — expect 0.
- [ ] **Step 3:** If anything fails, fix it in this task rather than leaving a broken commit — this task's sole deliverable is a fully green suite.
- [ ] **Step 4: Commit** (only if fixes were needed)

```bash
git add -A
git commit -m "fix: resolve i3X test-suite regressions found in full-suite run"
```

---

### Task 10: Vendor the spec snapshot, update docs, enable a real scenario

**Files:**
- Create: `docs/specs/i3x/openapi-1.0.0.json`, `docs/specs/i3x/IMPLEMENTATION_GUIDE.md`, `docs/specs/i3x/UNDERSTANDING_RELATIONSHIPS.md`
- Modify: `CLAUDE.md` (the "Candidate feature: i3X interface" section), `docs/ai_interface.md`, `README.md` (surfaces table), `config/scenarios.yaml` (enable `comms.i3x.enabled: true` on `demo_line`, so a fresh checkout has a working example)

- [ ] **Step 1:** Fetch and save the pinned OpenAPI document:

```bash
curl -sS https://api.i3x.dev/v1/openapi.json -o docs/specs/i3x/openapi-1.0.0.json
```

Fetch the two guide docs from the pinned commit:

```bash
mkdir -p docs/specs/i3x
gh api repos/cesmii/i3X/contents/spec/IMPLEMENTATION_GUIDE.md?ref=34b766442f6ef614d47fe905459a2ea8b91c6f8b -H "Accept: application/vnd.github.raw" > docs/specs/i3x/IMPLEMENTATION_GUIDE.md
gh api repos/cesmii/i3X/contents/spec/UNDERSTANDING_RELATIONSHIPS.md?ref=34b766442f6ef614d47fe905459a2ea8b91c6f8b -H "Accept: application/vnd.github.raw" > docs/specs/i3x/UNDERSTANDING_RELATIONSHIPS.md
```

- [ ] **Step 2:** In `CLAUDE.md`, replace the entire "## Candidate feature: i3X interface (under consideration — do not build without sign-off)" section with a short "implemented" note pointing at the design doc and the new module, in the same style as the existing "Publishers" section — describe what exists (`api/i3x.py`, `api/i3x_build.py`, `api/i3x_subscriptions.py`, `/i3x/v1` mounted at `:8080`, `comms.i3x.enabled` gate, no writes/no auth) rather than the old evaluation framing.

- [ ] **Step 3:** In `docs/ai_interface.md`, add a fourth row to the existing surfaces table (`| i3X interface | http://<host>:8080/i3x/v1/* | i3X-conformant test/reference clients |`) and a short section mirroring the existing "Knowledge graph"/"MCP server" sections — what it is, the enable flag, the explicit no-writes/no-auth notes, and a pointer to `docs/specs/i3x/`.

- [ ] **Step 4:** In `README.md`, add `i3X (test/reference interface)` to the protocol bullet list near the existing OPC UA/MQTT/SparkplugB mentions.

- [ ] **Step 5:** `demo_line` has no `comms:` block in the shipped `config/scenarios.yaml` today (verified — all protocols currently run on their defaults). Add one, right after its `sim_step: 1.0` line:

```yaml
  comms:
    i3x:
      enabled: true
```

so `python -m simengine --scenario demo_line` demonstrates the feature out of the box, without changing OPC UA/MQTT/SparkplugB's existing default behavior (they're unaffected by adding only an `i3x` key to a previously-absent `comms` block).

- [ ] **Step 6:** Run `pytest tests/ -v` once more (scenario file changed) and `flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source`.

- [ ] **Step 7: Commit**

```bash
git add docs/specs/i3x/ CLAUDE.md docs/ai_interface.md README.md config/scenarios.yaml
git commit -m "docs: vendor i3X 1.0.0 spec snapshot, document the shipped interface"
```

---

### Task 11: Manual cross-check against the pinned reference client (validation, not CI)

**Files:** none — this is a manual verification pass, per the design doc's Testing section ("not wired into CI").

- [ ] **Step 1:** Start simengine locally with `demo_line` (i3X now enabled per Task 10): `python -m simengine --scenario demo_line --seed 42`.
- [ ] **Step 2:** Fetch `demo/client/test_client.py` from the pinned commit (`gh api repos/cesmii/i3X/contents/demo/client/test_client.py?ref=34b766442f6ef614d47fe905459a2ea8b91c6f8b -H "Accept: application/vnd.github.raw"`), read it to see what it actually exercises against a server (it targets a base URL — check for a `--base-url`/env-var override rather than a hardcoded `localhost:8000` demo-server assumption), and either run it pointed at `http://localhost:8080/i3x/v1` or, if it hardcodes assumptions this server doesn't share (e.g. its own mock data source's specific element IDs), walk through its request/response assertions by hand against simengine's actual responses instead of running it verbatim.
- [ ] **Step 3:** Record the outcome — pass/fail per area checked — as a comment on this plan's tracking issue or PR, not as a new file. Any real mismatch found here is a bug against Tasks 3-8, not a reason to change the pinned spec.

---

## Notes for the implementer

- Task 6's `_resolve_value` is the one place in this plan whose exact attribute names weren't independently verified against `engine/snapshot.py` during planning (only inferred from `knowledge_graph.py`'s own field maps) — read that file first and correct names before writing the code, per the note inline in Task 6.
- Every `elementId` in this interface is a KG node id verbatim (`"station:Press01"`, `"metric:Press01.State"`, `"pv:Press01.OilTemp"`, ...) — never invent a separate i3X-only id scheme. This is what makes `/objects/related` a one-line KG edge walk instead of a translation layer.
- If a future task adds `historian-influx` support to `/objects/history`, only Task 6's `objects_history` route body changes — `i3x_build.py` and `i3x_subscriptions.py` are untouched by that.
