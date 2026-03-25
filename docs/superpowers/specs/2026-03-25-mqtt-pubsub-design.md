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

## Files

| File | Change |
|------|--------|
| `src/mqtt_publisher.py` | **New** — `MQTTPublisher` class |
| `docker/mosquitto/mosquitto.conf` | **New** — Mosquitto 2.0 config |
| `docker/mosquitto/passwd` | **New** — empty placeholder (anonymous auth for dev) |
| `docker/docker-compose.yml` | **Modified** — add `mosquitto` service |
| `requirements.txt` | **Modified** — add `paho-mqtt>=2.0.0` |
| `src/opcua_server.py` | **Modified** — `--mqtt` / `--mqtt-broker` flags, publisher lifecycle |
| `tests/test_mqtt_publisher.py` | **New** — unit tests (mock broker, no real connection) |

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

- MQTT 5.0 is supported by Mosquitto 2.0+ by default (no extra config required).
- Anonymous auth is acceptable for the dev/demo stack. Production upgrade path: set `allow_anonymous false` and add a `password_file` entry.
- Persistence ensures in-flight messages survive container restarts.

### `docker/docker-compose.yml` addition

```yaml
  mosquitto:
    image: eclipse-mosquitto:2.0
    container_name: mosquitto
    ports:
      - "1883:1883"      # MQTT
      - "9001:9001"      # WebSocket (for browser clients)
    volumes:
      - ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - mosquitto-data:/mosquitto/data
      - mosquitto-log:/mosquitto/log
    networks:
      - simantha-network
    restart: unless-stopped
```

Add to the `volumes:` section at the bottom of the file:
```yaml
  mosquitto-data:
  mosquitto-log:
```

The `simantha` service gains no new `depends_on` entry — MQTT is optional and the simulation must start even if Mosquitto is not up.

---

## CLI Flags

```bash
# Enable MQTT with default broker (mqtt://mosquitto:1883 → fallback localhost:1883)
python src/opcua_server.py --scenario full_feature_8_machine_line --mqtt

# Override broker URL
python src/opcua_server.py --scenario full_feature_8_machine_line \
    --mqtt --mqtt-broker mqtt://localhost:1883
```

Default broker resolution order:
1. `--mqtt-broker` argument if provided
2. `mqtt://mosquitto:1883` (Docker service name)
3. On connection failure: log warning, enter `disconnected` state, do not crash

---

## Topic Structure

Published every simulation step (1 second):

```
opcua/simantha/{run_id}/machines/M{i}    # Part 14 Network Message — per machine
opcua/simantha/{run_id}/system           # Part 14 Network Message — line KPIs
simantha/{run_id}/machines/M{i}         # Flat JSON — per machine
simantha/{run_id}/system                # Flat JSON — line KPIs
```

Total publishes per step: `2 formats × (N_machines + 1 system topic)`.
For the 8-machine scenario: 18 messages/step.

---

## Message Formats

### OPC UA Part 14 (pragmatic — key envelope fields, omits optional metadata/versioning)

Topic: `opcua/simantha/{run_id}/machines/M{i}`

```json
{
  "MessageId": "step-1234-M1",
  "MessageType": "ua-data",
  "PublisherId": "simantha-opcua",
  "DataSetWriterId": 1,
  "Timestamp": "2026-03-25T17:23:00Z",
  "Payload": {
    "State":       "PROCESSING",
    "OEE":         0.847,
    "PartCount":   412,
    "ActualPPM":   48.2,
    "HealthPct":   100.0,
    "Utilisation": 0.923,
    "DownTime":    4.0,
    "BlockedTime": 0.0,
    "StarvedTime": 12.0,
    "ProcessingTime": 1220.0,
    "IdleTime":    0.0,
    "GoodParts":   398,
    "DefectiveParts": 14,
    "BufferIn":    8,
    "BufferOut":   3,
    "Availability": 0.923,
    "Performance": 0.964,
    "Quality":     0.966,
    "TargetPPM":   50.0
  }
}
```

Topic: `opcua/simantha/{run_id}/system`

```json
{
  "MessageId": "step-1234-system",
  "MessageType": "ua-data",
  "PublisherId": "simantha-opcua",
  "DataSetWriterId": 100,
  "Timestamp": "2026-03-25T17:23:00Z",
  "Payload": {
    "SimTime":      1234.0,
    "LineState":    "RUNNING",
    "Throughput":   46.1,
    "TotalWIP":     23,
    "LineOEE":      0.831,
    "GoodParts":    3182,
    "DefectiveParts": 112,
    "TotalScrap":   58,
    "ScrapRate":    0.018,
    "MaintenanceQueueLength": 0
  }
}
```

### Flat JSON (plain MQTT subscribers)

Topic: `simantha/{run_id}/machines/M{i}`

```json
{
  "run_id":    "full_feature_8_machine_line_20260325_172300",
  "sim_time":  1234.0,
  "source":    "M1",
  "State":     "PROCESSING",
  "OEE":       0.847,
  "PartCount": 412,
  "ActualPPM": 48.2,
  "HealthPct": 100.0,
  "Utilisation": 0.923,
  "GoodParts": 398,
  "DefectiveParts": 14,
  "BufferIn":  8,
  "BufferOut": 3
}
```

### MQTT 5.0 Properties (applied to every message)

- `ContentType: application/json`
- `MessageExpiryInterval: 5` (seconds — stale steps auto-expire at broker)

**QoS: 0** on all topics. `publish()` returns immediately after enqueuing to paho's internal send buffer — never blocks the 1-second step clock.

---

## `MQTTPublisher` Class Design

```python
class MQTTPublisher:
    def __init__(self, broker_host: str, broker_port: int, run_id: str, flat: bool = True)
    def connect() -> None          # non-blocking; sets _connected flag; logs on failure
    def publish_step(
        machine_metrics: dict,     # {name: metrics_dict} from main loop
        buffers: dict,             # {name: buffer_obj}
        system_kpis: dict,         # throughput, wip, oee, etc.
        sim_time: float
    ) -> None
    def close() -> None            # disconnect; log dropped_steps count if > 0

    # private
    def _build_ua_message(source: str, payload: dict, step: int) -> str
    def _build_flat_message(source: str, payload: dict, sim_time: float) -> str
    def _publish(topic: str, payload_str: str) -> None   # QoS 0 + MQTT 5 props
```

`DataSetWriterId` assignment: machines use index `i` (1-based), system uses `100`.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Broker unreachable at startup | Log `WARNING: MQTT broker unreachable, publisher disabled`; simulation runs normally |
| Broker drops mid-run | paho-mqtt auto-reconnects in background; steps during reconnect dropped silently; `dropped_steps` counter incremented |
| `publish_step()` latency | Impossible with QoS 0 — returns immediately |
| Serialisation error | Log once per error type, skip that message, continue |

At `close()`: if `dropped_steps > 0`, log `INFO: MQTT publisher dropped N steps (broker unreachable)`.

---

## `opcua_server.py` Changes

1. Add `argparse` arguments:
   ```python
   parser.add_argument("--mqtt", action="store_true", help="Enable OPC UA PubSub over MQTT")
   parser.add_argument("--mqtt-broker", default="mqtt://mosquitto:1883",
                       help="MQTT broker URL (default: mqtt://mosquitto:1883)")
   ```

2. After existing historian setup, instantiate publisher:
   ```python
   mqtt_pub = None
   if args.mqtt:
       from mqtt_publisher import MQTTPublisher
       host, port = _parse_mqtt_url(args.mqtt_broker)
       mqtt_pub = MQTTPublisher(host, port, run_id)
       mqtt_pub.connect()
   ```

3. At the end of the per-step write block (after `update_shift_opcua_vars()`):
   ```python
   if mqtt_pub:
       mqtt_pub.publish_step(machine_metrics, buffers, system_kpis, sim_time)
   ```

4. In the shutdown/finally block:
   ```python
   if mqtt_pub:
       mqtt_pub.close()
   ```

`_parse_mqtt_url(url)` is a small helper that splits `mqtt://host:port` into `(host, port)`.

---

## Tests (`tests/test_mqtt_publisher.py`)

All tests use a monkeypatched `paho.mqtt.client.Client` — no real broker required.

| Test | Assertion |
|------|-----------|
| `test_publish_step_topic_count` | `publish()` called `2 × (N + 1)` times per step (both formats, all machines + system) |
| `test_ua_message_envelope` | Part 14 fields present: `MessageId`, `MessageType`, `PublisherId`, `DataSetWriterId`, `Timestamp`, `Payload` |
| `test_flat_message_fields` | `run_id`, `sim_time`, `source`, `State`, `OEE` present |
| `test_topic_format_machine` | Topic matches `opcua/simantha/{run_id}/machines/M1` |
| `test_topic_format_system` | Topic matches `opcua/simantha/{run_id}/system` |
| `test_disconnected_no_raise` | `publish_step()` in disconnected state does not raise |
| `test_dropped_steps_logged` | `close()` logs dropped count when broker was unreachable |

---

## Out of Scope

- TLS / mTLS for Mosquitto (production hardening, separate task)
- WebSocket listener on port 9001 is provisioned but not tested
- MQTT subscriber / consumer side
- Grafana MQTT datasource plugin
- `retain: true` on any topic (would require careful cleanup on run start)
