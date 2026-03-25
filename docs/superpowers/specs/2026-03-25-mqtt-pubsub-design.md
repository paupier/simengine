# OPC UA PubSub over MQTT — Design Spec

**Date:** 2026-03-25
**Status:** Approved

---

## Goal

Add an optional OPC UA PubSub over MQTT publisher as a bolt-on alongside the existing OPC UA TCP server. The existing OPC UA / Telegraf / InfluxDB / Grafana pipeline is completely unchanged. A new `--mqtt` CLI flag enables a per-step publisher that broadcasts simulation state to an Eclipse Mosquitto broker in two formats simultaneously.

---

## Architecture

```
Simulation step (1s wall-clock)
  → write_machine_opcua_vars()      ← unchanged
  → write_system_opcua_vars()       ← unchanged
  → update_shift_opcua_vars()       ← unchanged
  → record_historian_events()       ← unchanged
  → mqtt_publisher.publish_step()   ← NEW (only if --mqtt flag set)
```

The publisher is instantiated once at simulation startup (when `--mqtt` is present) and `close()`d on shutdown. If the broker is unreachable the simulation starts normally — MQTT is strictly additive.

---

## Files Changed

| File | Change |
|------|--------|
| `src/mqtt_publisher.py` | **New** — `MQTTPublisher` class |
| `docker/mosquitto/mosquitto.conf` | **New** — Mosquitto 2.0 config |
| `docker/docker-compose.yml` | **Modified** — add `mosquitto` service + named volumes |
| `requirements.txt` | **Modified** — add `paho-mqtt>=2.0.0` |
| `src/opcua_server.py` | **Modified** — `--mqtt`/`--mqtt-broker` argparse flags, publisher instantiation and lifecycle in `main()`, `publish_step()` call in `run_segment()` |
| `src/opcua_server.py` → `run_segment()` | **Modified** — gains `mqtt_publisher=None` keyword parameter |
| `src/recipe_runner.py` → `run_recipe()` | **Modified** — gains `mqtt_publisher=None` keyword parameter; passes it to each `run_segment()` call |
| `docker/webui/app.py` | **Modified** — forward `--mqtt` / `--mqtt-broker` flags in subprocess command builders (`start_simulation`, `start_simulation_recipe`) |
| `tests/test_mqtt_publisher.py` | **New** — unit tests (mock broker, no real connection) |

`docker/mosquitto/passwd` is **not** created — `allow_anonymous true` is used for the dev stack; no password file is needed or referenced.

---

## Docker — Mosquitto Provisioning

### `docker/mosquitto/mosquitto.conf`

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

MQTT 5.0 is supported by Mosquitto 2.0+ by default (no extra config required).
Anonymous auth is acceptable for the dev/demo stack.

### `docker/docker-compose.yml` — mosquitto service

Add inside the `services:` block. The network key is `simantha-net` (matches existing services):

```yaml
  mosquitto:
    image: eclipse-mosquitto:2.0
    container_name: mosquitto
    ports:
      - "1883:1883"
      - "9001:9001"
    volumes:
      - ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - mosquitto-data:/mosquitto/data
      - mosquitto-log:/mosquitto/log
    networks:
      - simantha-net
    restart: unless-stopped
```

Add to the `volumes:` section at the bottom of the file:

```yaml
  mosquitto-data:
  mosquitto-log:
```

The `simantha` service gains **no** new `depends_on` entry — MQTT is optional and the simulation must start even if Mosquitto is not up.

---

## CLI Flags

```bash
# Enable MQTT with default broker
python src/opcua_server.py --scenario full_feature_8_machine_line --mqtt

# Override broker URL
python src/opcua_server.py --scenario full_feature_8_machine_line \
    --mqtt --mqtt-broker mqtt://localhost:1883
```

`argparse` additions in `opcua_server.py`:

```python
parser.add_argument("--mqtt", action="store_true",
                    help="Enable OPC UA PubSub over MQTT publisher")
parser.add_argument("--mqtt-broker", default="mqtt://mosquitto:1883",
                    help="MQTT broker URL (default: mqtt://mosquitto:1883)")
```

`_parse_mqtt_url(url: str) -> tuple[str, int]`: splits `mqtt://host:port` and returns `(host, port)` as `(str, int)`. Raises `ValueError` with a descriptive message if the URL is malformed (missing port, non-`mqtt://` scheme). Called once at startup; any `ValueError` is caught, a warning logged, and the publisher is set to `None` (simulation continues without MQTT).

---

## Web UI Integration (`docker/webui/app.py`)

`start_simulation()` and `start_simulation_recipe()` build a subprocess `cmd` list. Add optional MQTT flag forwarding so the Web UI can also enable the publisher:

```python
if request.json.get("mqtt"):
    cmd += ["--mqtt"]
    broker = request.json.get("mqtt_broker", "")
    if broker:
        cmd += ["--mqtt-broker", broker]
```

The Web UI does not need a new page or form field for the presentation — the flags can be added to the existing JSON payload from the start button or left as a future enhancement. The code path must exist and be tested so it does not crash when the keys are absent.

---

## Topic Structure

Published every simulation step (1 second):

```
opcua/simantha/{run_id}/machines/M{i}    # Part 14 Network Message — per machine
opcua/simantha/{run_id}/system           # Part 14 Network Message — line KPIs
simantha/{run_id}/machines/M{i}         # Flat JSON — per machine
simantha/{run_id}/system                # Flat JSON — line KPIs
```

Total publishes per step: `2 × (N_machines + 1)`. For the 8-machine scenario: 18 messages/step.

---

## Message Formats

### OPC UA Part 14 envelope — machine

Topic: `opcua/simantha/{run_id}/machines/M{i}`

```json
{
  "MessageId": "step-1234-M1",
  "MessageType": "ua-data",
  "PublisherId": "simantha-opcua",
  "DataSetWriterId": 1,
  "Timestamp": "2026-03-25T17:23:00Z",
  "Payload": {
    "State":          "PROCESSING",
    "OEE":            0.847,
    "PartCount":      412,
    "ActualPPM":      48.2,
    "HealthPct":      100.0,
    "Utilisation":    0.923,
    "DownTime":       4.0,
    "BlockedTime":    0.0,
    "StarvedTime":    12.0,
    "ProcessingTime": 1220.0,
    "IdleTime":       0.0,
    "GoodParts":      398,
    "DefectiveParts": 14,
    "Availability":   0.923,
    "Performance":    0.964,
    "Quality":        0.966,
    "TargetPPM":      50.0
  }
}
```

`BufferIn` and `BufferOut` are **omitted** — per-machine buffer levels are not tracked in `machine_metrics` and would require traversing the topology at runtime. All other fields are present in `machine_metrics` (see data sources below).

### OPC UA Part 14 envelope — system

Topic: `opcua/simantha/{run_id}/system`

```json
{
  "MessageId": "step-1234-system",
  "MessageType": "ua-data",
  "PublisherId": "simantha-opcua",
  "DataSetWriterId": 100,
  "Timestamp": "2026-03-25T17:23:00Z",
  "Payload": {
    "SimTime":                  1234.0,
    "LineState":                "RUNNING",
    "Throughput":               46.1,
    "TotalWIP":                 23,
    "LineOEE":                  0.831,
    "GoodParts":                3182,
    "DefectiveParts":           112,
    "TotalScrap":               58,
    "ScrapRate":                0.018,
    "MaintenanceQueueLength":   0
  }
}
```

### Flat JSON — machine

Topic: `simantha/{run_id}/machines/M{i}`

```json
{
  "run_id":         "full_feature_8_machine_line_20260325_172300",
  "sim_time":       1234.0,
  "source":         "M1",
  "State":          "PROCESSING",
  "OEE":            0.847,
  "PartCount":      412,
  "ActualPPM":      48.2,
  "HealthPct":      100.0,
  "Utilisation":    0.923,
  "GoodParts":      398,
  "DefectiveParts": 14,
  "Availability":   0.923,
  "Performance":    0.964,
  "Quality":        0.966,
  "TargetPPM":      50.0
}
```

Both formats are always published. There is no `flat` toggle.

### MQTT 5.0 properties (every message)

- `ContentType: application/json`
- `MessageExpiryInterval: 5` (seconds — stale steps auto-expire at broker)
- **QoS: 0** — fire-and-forget; `publish()` returns immediately after enqueueing to paho's internal send buffer

`DataSetWriterId`: machines use 1-based index `i`, system uses `100`.

---

## Data Sources for `publish_step()`

`publish_step()` receives a `machine_snapshot` dict assembled at the call site in `run_segment()` immediately before the call. This avoids passing `opcua_vars` into the publisher.

### `machine_snapshot` dict assembled at call site

```python
machine_snapshot = {}
for mname, m in machines.items():
    mm = machine_metrics[mname]
    state = detect_machine_state(m, machine_health[mname], machine_metrics[mname])
    oee_c = mm.get("oee_cached", {})
    machine_snapshot[mname] = {
        "State":          state,
        "OEE":            oee_c.get("oee", 0.0),
        "Availability":   oee_c.get("availability", 0.0),
        "Performance":    oee_c.get("performance", 0.0),
        "Quality":        oee_c.get("quality", 0.0),
        "PartCount":      int(mm.get("partcount", 0)),
        "GoodParts":      int(mm.get("good_parts", 0)),
        "DefectiveParts": int(mm.get("defective_parts", 0)),
        "HealthPct":      round((1.0 - machine_health[mname] / max(getattr(machines[mname], "failed_health", 1), 1)) * 100, 1),
        "Utilisation":    round(mm.get("utilisation", 0.0), 4),
        "ActualPPM":      round(mm.get("actual_ppm", 0.0), 2),
        "TargetPPM":      round(mm.get("target_ppm", 0.0), 2),
        "DownTime":       round(mm.get("down_time", 0.0), 1),
        "BlockedTime":    round(mm.get("blocked_time", 0.0), 1),
        "StarvedTime":    round(mm.get("starved_time", 0.0), 1),
        "ProcessingTime": round(mm.get("processing_time", 0.0), 1),
        "IdleTime":       round(mm.get("idle_time", 0.0), 1),
    }
```

### `system_kpis` dict assembled at call site

```python
system_kpis = {
    "SimTime":                sim_time,
    "LineState":              line_state.state,
    "Throughput":             round(total_parts_produced / max(sim_time, 1) * 60, 2),
    "TotalWIP":               total_wip,
    "LineOEE":                round(line_oee, 4),
    "GoodParts":              int(line_state.good_parts),
    "DefectiveParts":         int(line_state.defective_parts),
    "TotalScrap":             int(total_scrap) if total_scrap is not None else 0,
    "ScrapRate":              round(scrap_rate, 4) if scrap_rate is not None else 0.0,
    "MaintenanceQueueLength": maint_queue_len,
}
```

`total_scrap`, `scrap_rate`, and `maint_queue_len` are local variables already present in `run_segment()` at the point of the call. `line_state.state` is the current `LineState.state` string (e.g. `"RUNNING"`).

---

## `MQTTPublisher` Class Interface

```python
class MQTTPublisher:
    def __init__(self, broker_host: str, broker_port: int, run_id: str)
    def connect() -> None
        # Calls paho client.connect(); on failure logs WARNING and sets _connected=False
        # Does NOT raise
    def publish_step(
        machine_snapshot: dict,   # {mname: field_dict} assembled at call site
        system_kpis: dict,        # assembled at call site
        sim_time: float,
        step: int                 # step_count for MessageId uniqueness
    ) -> None
        # If not _connected: increments dropped_steps, returns immediately
        # Otherwise: builds and publishes all messages QoS 0
    def close() -> None
        # Disconnects; logs "MQTT publisher dropped N steps" if dropped_steps > 0
    def _build_ua_message(source: str, payload: dict, step: int) -> str
    def _build_flat_message(source: str, payload: dict, sim_time: float) -> str
    def _publish(topic: str, payload_str: str) -> None
        # QoS 0; sets MQTT 5 properties ContentType and MessageExpiryInterval
```

paho reconnect: register `on_disconnect` callback that sets `_connected = False` and calls `client.reconnect_delay_set(1, 30)`. paho handles background reconnect automatically; `on_connect` callback sets `_connected = True`.

`dropped_steps` is a **lifetime cumulative counter** — never reset after reconnection. It accumulates across all disconnection periods and is reported once at `close()`. `test_reconnect_resets_counter` verifies that after `_connected` becomes `True` again, subsequent `publish_step()` calls do **not** increment `dropped_steps` further (counter stops, not resets).

---

## `run_segment()` Signature Change

`run_segment()` gains one new keyword parameter:

```python
def run_segment(..., mqtt_publisher=None):
```

At the end of the per-step write block (after `update_shift_opcua_vars()`), before `record_historian_events()`:

```python
if mqtt_publisher is not None:
    machine_snapshot = _build_machine_snapshot(machines, machine_metrics, machine_health)
    system_kpis = _build_system_kpis(sim_time, line_state, total_parts_produced,
                                      total_wip, line_oee, total_scrap, scrap_rate,
                                      maint_queue_len)
    mqtt_publisher.publish_step(machine_snapshot, system_kpis, sim_time, line_state.step_count)
```

`_build_machine_snapshot()` and `_build_system_kpis()` are module-level helpers in `opcua_server.py`:

```python
def _build_machine_snapshot(
    machines: dict,           # {mname: Machine}
    machine_metrics: dict,    # {mname: metrics_dict}
    machine_health: dict,     # {mname: int}
) -> dict:                    # returns {mname: field_dict}

def _build_system_kpis(
    sim_time: float,
    line_state,               # LineState instance
    total_parts_produced: int,
    total_wip: int,
    line_oee: float,
    total_scrap: int,
    scrap_rate: float,
    maint_queue_len: int,
) -> dict:
```

They are extracted as helpers to keep `run_segment()` readable and to make the publisher testable in isolation.

---

## Publisher Lifecycle

### Single-scenario mode (`main()`)

```python
mqtt_pub = None
if args.mqtt:
    from mqtt_publisher import MQTTPublisher
    try:
        host, port = _parse_mqtt_url(args.mqtt_broker)
        mqtt_pub = MQTTPublisher(host, port, run_id)
        mqtt_pub.connect()
    except ValueError as e:
        logger.warning(f"MQTT disabled: {e}")

try:
    run_segment(..., mqtt_publisher=mqtt_pub)
finally:
    if mqtt_pub:
        mqtt_pub.close()
```

### Recipe mode (`run_recipe()` in `recipe_runner.py`)

`mqtt_publisher` is passed through `args` (the existing `args` namespace already reaches `run_recipe()`). Add `mqtt_publisher` as an explicit parameter to `run_recipe()`:

```python
def run_recipe(recipe, seed, args, run_id, mqtt_publisher=None):
    ...
    run_segment(..., mqtt_publisher=mqtt_publisher)
```

`main()` passes `mqtt_pub` when calling `run_recipe()`. The single `MQTTPublisher` instance lives for the full recipe duration across all segments and changeovers. `close()` is called in `main()`'s `finally` block after `run_recipe()` returns.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Broker unreachable at startup | Log `WARNING`, `_connected=False`, simulation runs normally |
| Malformed `--mqtt-broker` URL | `ValueError` caught in `main()`, log warning, `mqtt_pub=None` |
| Broker drops mid-run | paho reconnects in background; steps during gap increment `dropped_steps`; no exception |
| Serialisation error | Log once per error type (use a `_logged_errors` set), skip that message, continue |
| `close()` | Disconnects; logs `dropped_steps` count if > 0 |

---

## Tests (`tests/test_mqtt_publisher.py`)

All tests monkeypatch `paho.mqtt.client.Client` — no real broker required.

| Test | Assertion |
|------|-----------|
| `test_publish_step_topic_count` | `publish()` called `2 × (N + 1)` times for N=3 machines |
| `test_ua_message_envelope` | `MessageId`, `MessageType`, `PublisherId`, `DataSetWriterId`, `Timestamp`, `Payload` all present |
| `test_flat_message_fields` | `run_id`, `sim_time`, `source`, `State`, `OEE` present |
| `test_topic_format_machine` | topic == `opcua/simantha/{run_id}/machines/M1` |
| `test_topic_format_system` | topic == `opcua/simantha/{run_id}/system` |
| `test_disconnected_no_raise` | `publish_step()` when `_connected=False` does not raise |
| `test_dropped_steps_incremented` | `dropped_steps` incremented on each call when `_connected=False` |
| `test_reconnect_resets_counter` | After `on_connect` fires, subsequent `publish_step()` calls succeed and do not increment `dropped_steps` |
| `test_parse_mqtt_url_valid` | `_parse_mqtt_url("mqtt://host:1883")` returns `("host", 1883)` |
| `test_parse_mqtt_url_invalid` | `_parse_mqtt_url("badurl")` raises `ValueError` |

---

## Out of Scope

- TLS / mTLS for Mosquitto (production hardening, separate task)
- WebSocket on port 9001 is provisioned but not tested
- MQTT subscriber / consumer side
- Grafana MQTT datasource plugin
- `retain: true` on any topic
- Web UI form field for enabling MQTT (flags can be added to start payload later)
