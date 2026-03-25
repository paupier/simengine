# OPC UA PubSub over MQTT — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `--mqtt` CLI flag that publishes per-step simulation snapshots to an Eclipse Mosquitto broker in OPC UA Part 14 JSON and flat JSON formats, bolt-on alongside the existing OPC UA TCP server.

**Architecture:** A new `MQTTPublisher` class in `src/mqtt_publisher.py` is instantiated in `main()` when `--mqtt` is set, passed as a keyword arg through `run_segment()` and `run_recipe()`, and called once per simulation step after `update_shift_opcua_vars()`. Two helper functions `_build_machine_snapshot()` and `_build_system_kpis()` assemble the data dicts at the call site. Mosquitto 2.0 is added as a new docker-compose service.

**Tech Stack:** `paho-mqtt>=2.0.0` (MQTT 5.0 support), Eclipse Mosquitto 2.0 Docker image, existing `opcua_server.py` per-step architecture.

**Spec:** `docs/superpowers/specs/2026-03-25-mqtt-pubsub-design.md`

---

## File Map

| File | Role |
|------|------|
| `src/mqtt_publisher.py` | **Create** — `MQTTPublisher` class + `_parse_mqtt_url()` |
| `tests/test_mqtt_publisher.py` | **Create** — 10 unit tests, mock paho client |
| `docker/mosquitto/mosquitto.conf` | **Create** — Mosquitto 2.0 config |
| `docker/docker-compose.yml` | **Modify** — add `mosquitto` service + named volumes |
| `requirements.txt` | **Modify** — add `paho-mqtt>=2.0.0` |
| `src/opcua_server.py` | **Modify** — `--mqtt`/`--mqtt-broker` flags, helper fns, `run_segment()` param + call |
| `src/recipe_runner.py` | **Modify** — `run_recipe()` gains `mqtt_publisher=None` param |
| `docker/webui/app.py` | **Modify** — forward `--mqtt`/`--mqtt-broker` in subprocess cmd builders |

---

## Task 1: `MQTTPublisher` class — core (no paho yet)

**Files:**
- Create: `src/mqtt_publisher.py`
- Create: `tests/test_mqtt_publisher.py`

- [ ] **Step 1.1: Add paho-mqtt to requirements.txt**

Open `requirements.txt` and add after the last non-comment line:

```
paho-mqtt>=2.0.0
```

Install it locally:

```bash
pip install paho-mqtt>=2.0.0
```

- [ ] **Step 1.2: Write failing tests for `_parse_mqtt_url`**

Create `tests/test_mqtt_publisher.py`:

```python
"""Tests for MQTTPublisher — all use a mock paho client, no real broker."""
import json
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# _parse_mqtt_url
# ---------------------------------------------------------------------------

def test_parse_mqtt_url_valid():
    from mqtt_publisher import _parse_mqtt_url
    host, port = _parse_mqtt_url("mqtt://mosquitto:1883")
    assert host == "mosquitto"
    assert port == 1883


def test_parse_mqtt_url_invalid_no_port():
    from mqtt_publisher import _parse_mqtt_url
    with pytest.raises(ValueError, match="port"):
        _parse_mqtt_url("mqtt://mosquitto")


def test_parse_mqtt_url_invalid_scheme():
    from mqtt_publisher import _parse_mqtt_url
    with pytest.raises(ValueError, match="mqtt://"):
        _parse_mqtt_url("tcp://mosquitto:1883")
```

- [ ] **Step 1.3: Run — expect ImportError (module doesn't exist yet)**

```bash
pytest tests/test_mqtt_publisher.py::test_parse_mqtt_url_valid -v
```

Expected: `ModuleNotFoundError: No module named 'mqtt_publisher'`

- [ ] **Step 1.4: Create `src/mqtt_publisher.py` with `_parse_mqtt_url` only**

```python
"""OPC UA PubSub over MQTT publisher (Part 14 JSON + flat JSON).

Activated by the --mqtt CLI flag. Non-blocking; QoS 0 fire-and-forget.
Broker unreachable → simulation continues normally, steps are dropped silently.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _parse_mqtt_url(url: str) -> tuple[str, int]:
    """Parse 'mqtt://host:port' → (host, port).

    Raises ValueError on malformed input.
    """
    if not url.startswith("mqtt://"):
        raise ValueError(f"MQTT broker URL must start with mqtt:// — got: {url!r}")
    rest = url[len("mqtt://"):]
    if ":" not in rest:
        raise ValueError(
            f"MQTT broker URL must include a port (e.g. mqtt://mosquitto:1883) — got: {url!r}"
        )
    host, port_str = rest.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        raise ValueError(f"MQTT broker port must be an integer — got: {port_str!r}")
    if not host:
        raise ValueError(f"MQTT broker URL has empty host — got: {url!r}")
    return host, port
```

- [ ] **Step 1.5: Run — expect the 3 parse tests to pass**

```bash
pytest tests/test_mqtt_publisher.py::test_parse_mqtt_url_valid \
       tests/test_mqtt_publisher.py::test_parse_mqtt_url_invalid_no_port \
       tests/test_mqtt_publisher.py::test_parse_mqtt_url_invalid_scheme -v
```

Expected: 3 passed

- [ ] **Step 1.6: Commit**

```bash
git add src/mqtt_publisher.py tests/test_mqtt_publisher.py requirements.txt
git commit -m "feat: add mqtt_publisher module skeleton + _parse_mqtt_url"
```

---

## Task 2: `MQTTPublisher` class — message building

**Files:**
- Modify: `src/mqtt_publisher.py`
- Modify: `tests/test_mqtt_publisher.py`

- [ ] **Step 2.1: Write failing tests for message format**

Append to `tests/test_mqtt_publisher.py`:

```python
# ---------------------------------------------------------------------------
# Helpers — shared test data
# ---------------------------------------------------------------------------

RUN_ID = "test_run_20260325_120000"

def _make_machine_snapshot(n=2):
    """Return a machine_snapshot dict with n machines (M1..Mn)."""
    snap = {}
    for i in range(1, n + 1):
        snap[f"M{i}"] = {
            "State": "PROCESSING",
            "OEE": 0.85,
            "Availability": 0.92,
            "Performance": 0.96,
            "Quality": 0.96,
            "PartCount": 100 * i,
            "GoodParts": 95 * i,
            "DefectiveParts": 5 * i,
            "HealthPct": 100.0,
            "Utilisation": 0.90,
            "ActualPPM": 48.0,
            "TargetPPM": 50.0,
            "DownTime": 0.0,
            "BlockedTime": 2.0,
            "StarvedTime": 3.0,
            "ProcessingTime": 55.0,
            "IdleTime": 0.0,
        }
    return snap


def _make_system_kpis():
    return {
        "SimTime": 120.0,
        "LineState": "RUNNING",
        "Throughput": 46.0,
        "TotalWIP": 10,
        "LineOEE": 0.83,
        "GoodParts": 950,
        "DefectiveParts": 50,
        "TotalScrap": 10,
        "ScrapRate": 0.01,
        "MaintenanceQueueLength": 0,
    }


def _make_publisher(run_id=RUN_ID):
    """Create MQTTPublisher with mocked paho Client."""
    from mqtt_publisher import MQTTPublisher
    with patch("mqtt_publisher.mqtt.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        pub = MQTTPublisher("localhost", 1883, run_id)
        pub._client = mock_client
        pub._connected = True   # skip real connect for message tests
    return pub, mock_client


# ---------------------------------------------------------------------------
# Message format tests
# ---------------------------------------------------------------------------

def test_ua_message_envelope():
    """Part 14 envelope must have all required top-level fields."""
    pub, _ = _make_publisher()
    snap = _make_machine_snapshot(1)
    msg_str = pub._build_ua_message("M1", snap["M1"], step=5)
    msg = json.loads(msg_str)
    for field in ("MessageId", "MessageType", "PublisherId", "DataSetWriterId",
                  "Timestamp", "Payload"):
        assert field in msg, f"Missing field: {field}"
    assert msg["MessageType"] == "ua-data"
    assert msg["PublisherId"] == "simantha-opcua"
    assert "M1" in msg["MessageId"]
    assert isinstance(msg["Payload"], dict)
    assert msg["Payload"]["State"] == "PROCESSING"


def test_flat_message_fields():
    """Flat JSON must include run_id, sim_time, source and key KPI fields."""
    pub, _ = _make_publisher()
    snap = _make_machine_snapshot(1)
    msg_str = pub._build_flat_message("M1", snap["M1"], sim_time=120.0)
    msg = json.loads(msg_str)
    for field in ("run_id", "sim_time", "source", "State", "OEE"):
        assert field in msg, f"Missing field: {field}"
    assert msg["run_id"] == RUN_ID
    assert msg["sim_time"] == 120.0
    assert msg["source"] == "M1"


def test_topic_format_machine():
    pub, _ = _make_publisher()
    # Verify topic string construction directly
    expected_ua = f"opcua/simantha/{RUN_ID}/machines/M1"
    expected_flat = f"simantha/{RUN_ID}/machines/M1"
    assert pub._machine_ua_topic("M1") == expected_ua
    assert pub._machine_flat_topic("M1") == expected_flat


def test_topic_format_system():
    pub, _ = _make_publisher()
    expected_ua = f"opcua/simantha/{RUN_ID}/system"
    expected_flat = f"simantha/{RUN_ID}/system"
    assert pub._system_ua_topic() == expected_ua
    assert pub._system_flat_topic() == expected_flat
```

- [ ] **Step 2.2: Run — expect AttributeError (methods don't exist)**

```bash
pytest tests/test_mqtt_publisher.py -k "ua_message or flat_message or topic_format" -v
```

Expected: `AttributeError: MQTTPublisher` (methods not yet defined)

- [ ] **Step 2.3: Add message-building methods to `MQTTPublisher`**

Append the full class to `src/mqtt_publisher.py` after `_parse_mqtt_url`:

```python
try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.properties import Properties
    from paho.mqtt.packettypes import PacketTypes
    _PAHO_AVAILABLE = True
except ImportError:
    mqtt = None  # type: ignore
    _PAHO_AVAILABLE = False


class MQTTPublisher:
    """Publishes per-step simulation snapshots to an MQTT broker.

    Two formats per step:
      opcua/simantha/{run_id}/machines/M{i}  — OPC UA Part 14 JSON Network Message
      opcua/simantha/{run_id}/system          — OPC UA Part 14 JSON (line KPIs)
      simantha/{run_id}/machines/M{i}         — flat JSON
      simantha/{run_id}/system                — flat JSON

    QoS 0 (fire-and-forget).  Never blocks the simulation step clock.
    If the broker is unreachable, dropped_steps is incremented and close()
    logs the total.
    """

    MESSAGE_EXPIRY_SECONDS = 5

    def __init__(self, broker_host: str, broker_port: int, run_id: str) -> None:
        self._host = broker_host
        self._port = broker_port
        self._run_id = run_id
        self._connected = False
        self._dropped_steps = 0
        self._logged_errors: set[str] = set()
        self._client: Optional[object] = None

    # ------------------------------------------------------------------
    # Topic helpers
    # ------------------------------------------------------------------

    def _machine_ua_topic(self, mname: str) -> str:
        return f"opcua/simantha/{self._run_id}/machines/{mname}"

    def _machine_flat_topic(self, mname: str) -> str:
        return f"simantha/{self._run_id}/machines/{mname}"

    def _system_ua_topic(self) -> str:
        return f"opcua/simantha/{self._run_id}/system"

    def _system_flat_topic(self) -> str:
        return f"simantha/{self._run_id}/system"

    # ------------------------------------------------------------------
    # Message builders
    # ------------------------------------------------------------------

    def _build_ua_message(self, source: str, payload: dict, step: int) -> str:
        """Build OPC UA Part 14 (pragmatic) JSON Network Message."""
        # DataSetWriterId: extract digit suffix from source (M1→1, system→100)
        try:
            writer_id = int("".join(c for c in source if c.isdigit()) or "100")
        except ValueError:
            writer_id = 100

        envelope = {
            "MessageId": f"step-{step}-{source}",
            "MessageType": "ua-data",
            "PublisherId": "simantha-opcua",
            "DataSetWriterId": writer_id,
            "Timestamp": datetime.now(timezone.utc).isoformat(),
            "Payload": payload,
        }
        return json.dumps(envelope, default=float)

    def _build_flat_message(self, source: str, payload: dict, sim_time: float) -> str:
        """Build flat JSON message with run_id, sim_time, source at top level."""
        msg = {
            "run_id": self._run_id,
            "sim_time": sim_time,
            "source": source,
        }
        msg.update(payload)
        return json.dumps(msg, default=float)

    # ------------------------------------------------------------------
    # Internal publish
    # ------------------------------------------------------------------

    def _publish(self, topic: str, payload_str: str) -> None:
        """Publish QoS 0 with MQTT 5.0 properties."""
        if not _PAHO_AVAILABLE or self._client is None:
            return
        try:
            props = Properties(PacketTypes.PUBLISH)
            props.ContentType = "application/json"
            props.MessageExpiryInterval = self.MESSAGE_EXPIRY_SECONDS
            self._client.publish(topic, payload_str, qos=0, properties=props)
        except Exception as e:
            key = type(e).__name__
            if key not in self._logged_errors:
                logger.warning("MQTT publish error (%s): %s", key, e)
                self._logged_errors.add(key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to broker.  On failure: log warning, set disconnected state."""
        if not _PAHO_AVAILABLE:
            logger.warning("paho-mqtt not installed; MQTT publisher disabled")
            return

        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                protocol=mqtt.MQTTv5,
            )

            def _on_connect(client, userdata, flags, reason_code, properties):
                if reason_code == 0:
                    self._connected = True
                    logger.info("MQTT connected to %s:%s", self._host, self._port)
                else:
                    logger.warning("MQTT connect refused: reason_code=%s", reason_code)

            def _on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
                self._connected = False
                logger.warning("MQTT disconnected (reason=%s); auto-reconnecting…", reason_code)
                client.reconnect_delay_set(min_delay=1, max_delay=30)

            client.on_connect = _on_connect
            client.on_disconnect = _on_disconnect
            client.connect_async(self._host, self._port)
            client.loop_start()
            self._client = client
        except Exception as e:
            logger.warning("MQTT broker unreachable (%s); publisher disabled", e)
            self._connected = False

    def publish_step(
        self,
        machine_snapshot: dict,
        system_kpis: dict,
        sim_time: float,
        step: int,
    ) -> None:
        """Publish one step's worth of data.  QoS 0; never blocks."""
        if not self._connected:
            self._dropped_steps += 1
            return

        try:
            # Per-machine messages
            for mname, payload in machine_snapshot.items():
                ua_msg = self._build_ua_message(mname, payload, step)
                flat_msg = self._build_flat_message(mname, payload, sim_time)
                self._publish(self._machine_ua_topic(mname), ua_msg)
                self._publish(self._machine_flat_topic(mname), flat_msg)

            # System message
            ua_sys = self._build_ua_message("system", system_kpis, step)
            flat_sys = self._build_flat_message("system", system_kpis, sim_time)
            self._publish(self._system_ua_topic(), ua_sys)
            self._publish(self._system_flat_topic(), flat_sys)

        except Exception as e:
            key = f"publish_step:{type(e).__name__}"
            if key not in self._logged_errors:
                logger.warning("MQTT publish_step error: %s", e)
                self._logged_errors.add(key)
            self._dropped_steps += 1

    def close(self) -> None:
        """Disconnect and log dropped step count."""
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        if self._dropped_steps > 0:
            logger.info(
                "MQTT publisher closed — dropped %d steps (broker unavailable)",
                self._dropped_steps,
            )
```

- [ ] **Step 2.4: Run the message format tests**

```bash
pytest tests/test_mqtt_publisher.py -k "ua_message or flat_message or topic_format" -v
```

Expected: 4 passed

- [ ] **Step 2.5: Commit**

```bash
git add src/mqtt_publisher.py tests/test_mqtt_publisher.py
git commit -m "feat: implement MQTTPublisher message building and topic helpers"
```

---

## Task 3: `MQTTPublisher` — connection and publish_step tests

**Files:**
- Modify: `tests/test_mqtt_publisher.py`

- [ ] **Step 3.1: Write failing tests for publish_step and disconnected state**

Append to `tests/test_mqtt_publisher.py`:

```python
# ---------------------------------------------------------------------------
# publish_step tests
# ---------------------------------------------------------------------------

def test_publish_step_topic_count():
    """publish() must be called 2 × (N_machines + 1) times per step."""
    from mqtt_publisher import MQTTPublisher
    with patch("mqtt_publisher.mqtt") as mock_mqtt_module, \
         patch("mqtt_publisher._PAHO_AVAILABLE", True):
        mock_client = MagicMock()
        mock_mqtt_module.Client.return_value = mock_client
        mock_mqtt_module.CallbackAPIVersion.VERSION2 = "v2"
        mock_mqtt_module.MQTTv5 = 5

        pub = MQTTPublisher("localhost", 1883, RUN_ID)
        pub._client = mock_client
        pub._connected = True

        # Also mock Properties/PacketTypes so _publish doesn't blow up
        with patch("mqtt_publisher.Properties"), patch("mqtt_publisher.PacketTypes"):
            n = 3
            pub.publish_step(_make_machine_snapshot(n), _make_system_kpis(),
                             sim_time=120.0, step=5)

        expected_calls = 2 * (n + 1)   # 2 formats × (3 machines + 1 system)
        assert mock_client.publish.call_count == expected_calls


def test_disconnected_no_raise():
    """publish_step() when _connected=False must not raise."""
    from mqtt_publisher import MQTTPublisher
    pub = MQTTPublisher("localhost", 1883, RUN_ID)
    pub._connected = False
    # Should return silently
    pub.publish_step(_make_machine_snapshot(2), _make_system_kpis(),
                     sim_time=10.0, step=1)


def test_dropped_steps_incremented():
    """dropped_steps increments on each publish_step call when disconnected."""
    from mqtt_publisher import MQTTPublisher
    pub = MQTTPublisher("localhost", 1883, RUN_ID)
    pub._connected = False
    pub.publish_step(_make_machine_snapshot(2), _make_system_kpis(), 1.0, 1)
    pub.publish_step(_make_machine_snapshot(2), _make_system_kpis(), 2.0, 2)
    assert pub._dropped_steps == 2


def test_reconnect_resets_counter():
    """After _connected becomes True, publish_step does NOT increment dropped_steps."""
    from mqtt_publisher import MQTTPublisher
    pub = MQTTPublisher("localhost", 1883, RUN_ID)
    pub._connected = False
    pub._client = MagicMock()

    pub.publish_step(_make_machine_snapshot(1), _make_system_kpis(), 1.0, 1)
    assert pub._dropped_steps == 1

    # Simulate reconnect
    pub._connected = True
    with patch("mqtt_publisher.Properties"), patch("mqtt_publisher.PacketTypes"), \
         patch("mqtt_publisher._PAHO_AVAILABLE", True):
        pub.publish_step(_make_machine_snapshot(1), _make_system_kpis(), 2.0, 2)

    # Counter must NOT have changed
    assert pub._dropped_steps == 1
```

- [ ] **Step 3.2: Run — expect failures**

```bash
pytest tests/test_mqtt_publisher.py -k "topic_count or no_raise or incremented or reconnect" -v
```

Expected: failures (method exists but patching pattern not yet validated)

- [ ] **Step 3.3: Run all mqtt tests**

```bash
pytest tests/test_mqtt_publisher.py -v
```

Expected: all 10 tests pass (the implementation from Task 2 already covers this logic)

If any fail, check the patch paths in the tests match the import names in `mqtt_publisher.py`.

- [ ] **Step 3.4: Commit**

```bash
git add tests/test_mqtt_publisher.py
git commit -m "test: complete MQTTPublisher test suite (10 tests)"
```

---

## Task 4: `opcua_server.py` — data assembly helpers

**Files:**
- Modify: `src/opcua_server.py` (after line 2480, before `_apply_demo_flags`)

- [ ] **Step 4.1: Add `_build_machine_snapshot` and `_build_system_kpis` helpers**

Insert the two helper functions **after line 2481** (the blank line after `return sim_time, total_parts_produced, stop_reason, line_oee`), before the `def _apply_demo_flags` definition at line 2483:

```python
def _build_machine_snapshot(
    machines: dict,
    machine_metrics: dict,
    machine_health: dict,
) -> dict:
    """Assemble per-machine field dict for MQTTPublisher.publish_step().

    Reads from machine_metrics (accumulated per-step) and machine_health
    (health state counter carried across steps).
    """
    snapshot = {}
    for mname, mobj in machines.items():
        mm = machine_metrics[mname]
        health = machine_health.get(mname, 0)
        failed_health = getattr(mobj, "failed_health", 1)
        oee_c = mm.get("oee_cached", {})

        # maint_active mirrors the logic in process_machine_step (line 1119)
        maint_active = getattr(mobj, "under_repair", False)

        # Utilisation: processing_time / total active time
        total_time = (mm.get("processing_time", 0.0) + mm.get("blocked_time", 0.0) +
                      mm.get("starved_time", 0.0) + mm.get("down_time", 0.0) +
                      mm.get("idle_time", 0.0))
        utilisation = mm.get("processing_time", 0.0) / total_time if total_time > 0 else 0.0

        # ActualPPM: parts per minute over elapsed sim time
        total_time_min = total_time / 60.0
        actual_ppm = mm.get("partcount", 0) / total_time_min if total_time_min > 0 else 0.0

        # HealthPct: 0=fully healthy, failed_health=failed; invert to percentage
        health_pct = round((1.0 - health / max(failed_health, 1)) * 100.0, 1)
        health_pct = max(0.0, min(100.0, health_pct))

        snapshot[mname] = {
            "State":          detect_machine_state(mobj, health, maint_active),
            "OEE":            round(oee_c.get("oee", 0.0), 4),
            "Availability":   round(oee_c.get("availability", 0.0), 4),
            "Performance":    round(oee_c.get("performance", 0.0), 4),
            "Quality":        round(oee_c.get("quality", 0.0), 4),
            "PartCount":      int(mm.get("partcount", 0)),
            "GoodParts":      int(mm.get("good_parts", 0)),
            "DefectiveParts": int(mm.get("defective_parts", 0)),
            "HealthPct":      health_pct,
            "Utilisation":    round(utilisation, 4),
            "ActualPPM":      round(actual_ppm, 2),
            "TargetPPM":      round(mm.get("target_ppm", 0.0), 2),
            "DownTime":       round(mm.get("down_time", 0.0), 1),
            "BlockedTime":    round(mm.get("blocked_time", 0.0), 1),
            "StarvedTime":    round(mm.get("starved_time", 0.0), 1),
            "ProcessingTime": round(mm.get("processing_time", 0.0), 1),
            "IdleTime":       round(mm.get("idle_time", 0.0), 1),
        }
    return snapshot


def _build_system_kpis(
    sim_time: float,
    line_state,
    total_parts_produced: int,
    total_wip: int,
    line_oee: float,
    total_scrap: int,
    scrap_rate: float,
    maint_queue_len: int,
) -> dict:
    """Assemble system-level KPI dict for MQTTPublisher.publish_step()."""
    total_time_min = sim_time / 60.0
    throughput = round(total_parts_produced / total_time_min, 2) if total_time_min > 0 else 0.0
    return {
        "SimTime":                sim_time,
        "LineState":              getattr(line_state, "state", "RUNNING"),
        "Throughput":             throughput,
        "TotalWIP":               int(total_wip),
        "LineOEE":                round(line_oee, 4),
        "GoodParts":              int(getattr(line_state, "good_parts", 0)),
        "DefectiveParts":         int(getattr(line_state, "defective_parts", 0)),
        "TotalScrap":             int(total_scrap) if total_scrap is not None else 0,
        "ScrapRate":              round(scrap_rate, 4) if scrap_rate is not None else 0.0,
        "MaintenanceQueueLength": int(maint_queue_len),
    }
```

**Note:** `detect_machine_state` is already defined in the same file (`opcua_server.py`, line 526) — no import needed. The three-arg call `detect_machine_state(mobj, health, maint_active)` is required so that machines under repair show `UNDER_REPAIR` rather than `FAILED` in the MQTT snapshot.

- [ ] **Step 4.2: Verify the helpers are syntactically correct**

```bash
python -c "import sys; sys.path.insert(0, 'src'); import opcua_server; print('OK')"
```

Expected: `OK` (no ImportError or SyntaxError)

- [ ] **Step 4.3: Commit**

```bash
git add src/opcua_server.py
git commit -m "feat: add _build_machine_snapshot and _build_system_kpis helpers to opcua_server"
```

---

## Task 5: `opcua_server.py` — `run_segment` integration + CLI flags

**Files:**
- Modify: `src/opcua_server.py`

- [ ] **Step 5.1: Add `mqtt_publisher=None` to `run_segment` signature**

At line 2117 (`recipe_vars=None,`), add one line after it:

```python
    mqtt_publisher=None,
```

So the full tail of the signature becomes:
```python
    shift_manager=None,
    historian=None,
    neo4j_hist=None,
    recipe_vars=None,
    mqtt_publisher=None,
):
```

- [ ] **Step 5.2a: Capture `total_scrap` from `update_scrap_tracking`**

`update_scrap_tracking` already returns `total_scrap` (see its docstring at line 1373). Currently its return value is discarded at line 2442. Change line 2442–2443 from:

```python
        update_scrap_tracking(scrap_sinks, total_parts_produced, opcua_vars,
                              scrap_totals=scrap_totals)
```

to:

```python
        total_scrap = update_scrap_tracking(scrap_sinks, total_parts_produced, opcua_vars,
                                            scrap_totals=scrap_totals)
        _total_output = total_parts_produced + total_scrap
        scrap_rate = total_scrap / _total_output if _total_output > 0 else 0.0
```

`total_scrap` will be `0` for scenarios without scrap sinks (correct).

- [ ] **Step 5.2b: Add the `publish_step` call inside `run_segment`**

After line 2460 (`update_shift_opcua_vars(shift_manager, opcua_vars, sim_time, delta_parts)`), and before the `# Update recipe OPC UA vars` block, insert:

```python
        # MQTT PubSub — publish full snapshot if enabled
        if mqtt_publisher is not None:
            _machine_snap = _build_machine_snapshot(machines, machine_metrics, machine_health)
            _sys_kpis = _build_system_kpis(
                sim_time, line_state, total_parts_produced, total_wip, line_oee,
                total_scrap, scrap_rate, maint_queue_length,
            )
            mqtt_publisher.publish_step(_machine_snap, _sys_kpis, sim_time, line_state.step_count)
```

**Verify variable names:** `total_wip`, `line_oee`, and `maint_queue_length` are confirmed local variables in `run_segment` at this point. If any name differs in the actual code, use what grep shows:
```bash
grep -n "total_wip\s*=\|line_oee\s*=\|maint_queue_length\s*=" src/opcua_server.py | head -10
```

- [ ] **Step 5.3: Add `--mqtt` and `--mqtt-broker` argparse arguments**

In `main()`, after line 2515 (`parser.add_argument("--interarrival-time"...)`), add:

```python
    parser.add_argument("--mqtt", action="store_true",
                        help="Enable OPC UA PubSub over MQTT publisher")
    parser.add_argument("--mqtt-broker", default="mqtt://mosquitto:1883",
                        dest="mqtt_broker",
                        help="MQTT broker URL (default: mqtt://mosquitto:1883)")
```

- [ ] **Step 5.4: Add publisher instantiation in `main()` after historian setup**

After line 2594 (`print(f"  Neo4j historian enabled: ...")`), insert:

```python
    # Create MQTT publisher if --mqtt flag set
    mqtt_pub = None
    if args.mqtt:
        try:
            from mqtt_publisher import MQTTPublisher, _parse_mqtt_url
            host, port = _parse_mqtt_url(args.mqtt_broker)
            mqtt_pub = MQTTPublisher(host, port, run_id)
            mqtt_pub.connect()
            print(f"  MQTT publisher enabled: {args.mqtt_broker}")
        except (ValueError, Exception) as e:
            print(f"  MQTT publisher disabled: {e}")
            mqtt_pub = None
```

- [ ] **Step 5.5: Pass `mqtt_publisher` to `run_segment` in single-scenario mode**

At line 2602 (`run_segment(`), add `mqtt_publisher=mqtt_pub,` to the keyword argument list:

```python
        run_segment(
            ...
            neo4j_hist=neo4j_hist,
            mqtt_publisher=mqtt_pub,
        )
```

- [ ] **Step 5.6: Add `mqtt_pub.close()` to the `finally` block**

After line 2675 (`server.stop()`), inside the `finally` block, add:

```python
        if mqtt_pub:
            mqtt_pub.close()
```

- [ ] **Step 5.7: Verify server imports cleanly**

```bash
python -c "import sys; sys.path.insert(0, 'src'); import opcua_server; print('OK')"
```

Expected: `OK`

- [ ] **Step 5.8: Run full non-integration test suite**

```bash
pytest tests/ -v --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py -q
```

Expected: same pass count as before (no regressions). Check the count against memory: 511 non-integration tests.

- [ ] **Step 5.9: Commit**

```bash
git add src/opcua_server.py
git commit -m "feat: wire --mqtt flag and publish_step into run_segment and main()"
```

---

## Task 6: `recipe_runner.py` — recipe mode integration

**Files:**
- Modify: `src/recipe_runner.py`

- [ ] **Step 6.1: Add `mqtt_publisher=None` to `run_recipe` signature**

At line 392, change:
```python
def run_recipe(
    recipe: RecipeConfig,
    sim_seed: int,
    args,
    run_id: str,
):
```
to:
```python
def run_recipe(
    recipe: RecipeConfig,
    sim_seed: int,
    args,
    run_id: str,
    mqtt_publisher=None,
):
```

- [ ] **Step 6.2: Pass `mqtt_publisher` into each `run_segment` call**

At line 524, add `mqtt_publisher=mqtt_publisher,` to the `run_segment(...)` keyword arguments, after `neo4j_hist=neo4j_hist,`:

```python
                run_segment(
                    ...
                    neo4j_hist=neo4j_hist,
                    recipe_vars=recipe_vars,
                    mqtt_publisher=mqtt_publisher,
                )
```

- [ ] **Step 6.3: Restructure `main()` to handle `mqtt_pub` in both branches**

`run_id` is computed differently in recipe mode vs single-scenario mode, so `mqtt_pub` must be instantiated **inside each branch**, immediately after `run_id` is known. The Task 5.4 block was added only inside the single-scenario path — now add an equivalent block inside the recipe branch too.

Declare `mqtt_pub = None` once before the `if args.recipe:` fork (around line 2533):

```python
    mqtt_pub = None
```

**Inside the recipe branch** (after `run_id = ...` and before `run_recipe(...)`), add:

```python
        if args.mqtt:
            try:
                from mqtt_publisher import MQTTPublisher, _parse_mqtt_url
                host, port = _parse_mqtt_url(args.mqtt_broker)
                mqtt_pub = MQTTPublisher(host, port, run_id)
                mqtt_pub.connect()
                print(f"  MQTT publisher enabled: {args.mqtt_broker}")
            except Exception as e:
                print(f"  MQTT publisher disabled: {e}")
```

Change the `run_recipe(...)` call (line 2548) to:
```python
        run_recipe(recipe, sim_seed, args, run_id, mqtt_publisher=mqtt_pub)
```

Add `mqtt_pub.close()` immediately after `run_recipe(...)` returns (before `return`):
```python
        if mqtt_pub:
            mqtt_pub.close()
        return
```

The single-scenario branch already has the `mqtt_pub` instantiation from Task 5.4, and `mqtt_pub.close()` in its `finally` block from Task 5.6. No changes needed there.

Final structure of `main()`:

```python
    mqtt_pub = None

    if args.recipe:
        ...
        run_id = f"{args.recipe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if args.mqtt:
            try:
                from mqtt_publisher import MQTTPublisher, _parse_mqtt_url
                host, port = _parse_mqtt_url(args.mqtt_broker)
                mqtt_pub = MQTTPublisher(host, port, run_id)
                mqtt_pub.connect()
                print(f"  MQTT publisher enabled: {args.mqtt_broker}")
            except Exception as e:
                print(f"  MQTT publisher disabled: {e}")
        run_recipe(recipe, sim_seed, args, run_id, mqtt_publisher=mqtt_pub)
        if mqtt_pub:
            mqtt_pub.close()
        return

    # single-scenario path  (mqtt_pub instantiated in Task 5.4, closed in Task 5.6 finally)
    run_id = f"{args.scenario}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    ...
```

In `main()`, remove the standalone `mqtt_pub = None` that was placed after historian setup in Task 5.4 and replace with the pattern above.

```python
    mqtt_pub = None

    if args.recipe:
        ...
        run_id = ...
        if args.mqtt:
            try:
                from mqtt_publisher import MQTTPublisher, _parse_mqtt_url
                host, port = _parse_mqtt_url(args.mqtt_broker)
                mqtt_pub = MQTTPublisher(host, port, run_id)
                mqtt_pub.connect()
                print(f"  MQTT publisher enabled: {args.mqtt_broker}")
            except Exception as e:
                print(f"  MQTT publisher disabled: {e}")
        run_recipe(recipe, sim_seed, args, run_id, mqtt_publisher=mqtt_pub)
        if mqtt_pub:
            mqtt_pub.close()
        return

    # single-scenario path
    run_id = ...
    if args.mqtt:
        try:
            from mqtt_publisher import MQTTPublisher, _parse_mqtt_url
            host, port = _parse_mqtt_url(args.mqtt_broker)
            mqtt_pub = MQTTPublisher(host, port, run_id)
            mqtt_pub.connect()
            print(f"  MQTT publisher enabled: {args.mqtt_broker}")
        except Exception as e:
            print(f"  MQTT publisher disabled: {e}")
    ...
    try:
        run_segment(..., mqtt_publisher=mqtt_pub)
    finally:
        ...
        if mqtt_pub:
            mqtt_pub.close()
```

- [ ] **Step 6.4: Run tests**

```bash
pytest tests/ -q --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py
```

Expected: same pass count, 0 failures.

- [ ] **Step 6.5: Commit**

```bash
git add src/recipe_runner.py src/opcua_server.py
git commit -m "feat: thread mqtt_publisher through run_recipe() and both main() branches"
```

---

## Task 7: Web UI — forward `--mqtt` flag

**Files:**
- Modify: `docker/webui/app.py`

The `--mqtt` flag is forwarded from the JSON body of `POST /api/start` and `POST /api/start-recipe`, not from persisted settings. This keeps it per-request (same pattern as `seed` and `interarrival_time`).

- [ ] **Step 7.1: Add `mqtt` and `mqtt_broker` parameters to `start_simulation`**

`start_simulation()` signature (line 337) becomes:

```python
def start_simulation(scenario, seed=None, interarrival_time=None, mqtt=False, mqtt_broker=""):
```

After the `demo_mode` check (line 357), add:

```python
        if mqtt:
            cmd.append("--mqtt")
            if mqtt_broker:
                cmd += ["--mqtt-broker", mqtt_broker]
```

- [ ] **Step 7.2: Add the same parameters to `start_simulation_recipe`**

`start_simulation_recipe()` signature (line 386) becomes:

```python
def start_simulation_recipe(recipe_name, seed=None, interarrival_time=None, mqtt=False, mqtt_broker=""):
```

After the `demo_mode` check (line 410), add the same block:

```python
        if mqtt:
            cmd.append("--mqtt")
            if mqtt_broker:
                cmd += ["--mqtt-broker", mqtt_broker]
```

- [ ] **Step 7.3: Read `mqtt`/`mqtt_broker` from request JSON in `api_start`**

In `api_start()` (line 688), after `interarrival_time = data.get("interarrival_time")` (line 693), add:

```python
    mqtt = bool(data.get("mqtt", False))
    mqtt_broker = data.get("mqtt_broker", "")
```

Change the `start_simulation(...)` call (line 714) to:

```python
    start_simulation(scenario, seed, interarrival_time, mqtt=mqtt, mqtt_broker=mqtt_broker)
```

- [ ] **Step 7.4: Read `mqtt`/`mqtt_broker` from request JSON in `api_start_recipe`**

In `api_start_recipe()` (line 961), after `interarrival_time = data.get("interarrival_time")` (line 971), add:

```python
    mqtt = bool(data.get("mqtt", False))
    mqtt_broker = data.get("mqtt_broker", "")
```

Change the `start_simulation_recipe(...)` call (line 995) to:

```python
    start_simulation_recipe(recipe_name, seed, interarrival_time, mqtt=mqtt, mqtt_broker=mqtt_broker)
```

- [ ] **Step 7.5: Write a test for the flag forwarding**

Add to `tests/test_webui.py` (find the existing test file and add at the end):

```python
def test_api_start_forwards_mqtt_flag(client, mocker):
    """--mqtt and --mqtt-broker must appear in the subprocess cmd when mqtt=True."""
    mock_popen = mocker.patch("app.subprocess.Popen")
    mock_popen.return_value.poll.return_value = None
    mock_popen.return_value.stdout = iter([])

    resp = client.post("/api/start", json={
        "scenario": "balanced_line",
        "mqtt": True,
        "mqtt_broker": "mqtt://testbroker:1883",
    })
    assert resp.status_code == 200
    cmd = mock_popen.call_args[0][0]
    assert "--mqtt" in cmd
    assert "--mqtt-broker" in cmd
    assert "mqtt://testbroker:1883" in cmd


def test_api_start_no_mqtt_flag_by_default(client, mocker):
    """--mqtt must NOT appear in subprocess cmd when mqtt key absent."""
    mock_popen = mocker.patch("app.subprocess.Popen")
    mock_popen.return_value.poll.return_value = None
    mock_popen.return_value.stdout = iter([])

    resp = client.post("/api/start", json={"scenario": "balanced_line"})
    assert resp.status_code == 200
    cmd = mock_popen.call_args[0][0]
    assert "--mqtt" not in cmd
```

Check the existing `test_webui.py` for the `client` and `mocker` fixture patterns — match exactly what the other tests use.

- [ ] **Step 7.6: Run web UI tests**

```bash
pytest tests/test_webui.py -q
```

Expected: all pass.

- [ ] **Step 7.7: Verify Flask app imports cleanly**

```bash
python -c "import sys; sys.path.insert(0, 'docker/webui'); import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 7.8: Commit**

```bash
git add docker/webui/app.py tests/test_webui.py
git commit -m "feat: forward --mqtt/--mqtt-broker flags from web UI subprocess launcher"
```

---

## Task 8: Docker — Mosquitto service

**Files:**
- Create: `docker/mosquitto/mosquitto.conf`
- Modify: `docker/docker-compose.yml`

- [ ] **Step 8.1: Create Mosquitto config file**

Create `docker/mosquitto/mosquitto.conf`:

```
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
log_dest stdout
log_type error
log_type warning
log_type information
```

- [ ] **Step 8.2: Add `mosquitto` service to `docker/docker-compose.yml`**

After the `neodash` service block (line 152), insert:

```yaml
  # -------------------------------------------------------------------------
  # Eclipse Mosquitto 2.0 - MQTT Broker (OPC UA PubSub transport)
  # -------------------------------------------------------------------------
  mosquitto:
    image: eclipse-mosquitto:2.0
    container_name: simantha-mosquitto
    ports:
      - "1883:1883"      # MQTT
      - "9001:9001"      # WebSocket (for browser MQTT clients)
    volumes:
      - ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - mosquitto-data:/mosquitto/data
      - mosquitto-log:/mosquitto/log
    networks:
      - simantha-net
    restart: unless-stopped
```

- [ ] **Step 8.3: Add named volumes to the `volumes:` section**

After `neo4j-logs:` (line 166), add:

```yaml
  mosquitto-data:
    name: simantha-mosquitto-data
  mosquitto-log:
    name: simantha-mosquitto-log
```

- [ ] **Step 8.4: Update the header comment**

In the compose file header (around line 14), add `mosquitto` to the services list:

```yaml
#   - mosquitto: MQTT broker (:1883)
```

- [ ] **Step 8.5: Validate compose file syntax**

```bash
docker compose -f docker/docker-compose.yml config --quiet
```

Expected: exits 0 (no output = valid)

- [ ] **Step 8.6: Commit**

```bash
git add docker/mosquitto/mosquitto.conf docker/docker-compose.yml
git commit -m "feat: add Eclipse Mosquitto 2.0 broker to docker-compose stack"
```

---

## Task 9: End-to-end smoke test

- [ ] **Step 9.1: Run full test suite one final time**

```bash
pytest tests/ -q --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py
```

Expected: all tests pass, no new failures.

- [ ] **Step 9.2: Local smoke test — start server with `--mqtt`**

In one terminal:

```bash
# Start a local Mosquitto (or use Docker)
docker run -d --rm -p 1883:1883 eclipse-mosquitto:2.0 \
    sh -c "echo 'listener 1883\nallow_anonymous true' > /tmp/m.conf && mosquitto -c /tmp/m.conf"

# Subscribe to all simantha topics
docker run --rm --network host eclipse-mosquitto:2.0 \
    mosquitto_sub -h localhost -p 1883 -t "simantha/#" -v
```

In another terminal:

```bash
python src/opcua_server.py --scenario balanced_line --mqtt --mqtt-broker mqtt://localhost:1883 --seed 42
```

Expected: JSON messages appear in the subscriber terminal every second on `simantha/{run_id}/machines/M1` etc.

- [ ] **Step 9.3: Verify Part 14 envelope**

From the subscriber output, confirm one machine message contains:
- `MessageId`, `MessageType: "ua-data"`, `PublisherId: "simantha-opcua"`, `Payload` with `State` field

- [ ] **Step 9.4: Final commit and push**

```bash
git push
```

---

## Quick Reference — Variable Names in `run_segment`

Before implementing Task 5, confirm exact local variable names with:

```bash
grep -n "maint_queue_length\|total_scrap\|scrap_rate\|total_wip\|line_oee\|line_state" \
    src/opcua_server.py | grep -v "def \|#" | head -20
```

These are the names to pass to `_build_system_kpis()`. If the name differs (e.g. `maint_queue_len` vs `maint_queue_length`) use whatever the grep shows.
