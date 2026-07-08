# Clone Target Architecture — Lean Core + Optional Plugins

**Status:** Proposed
**Refines:** `clone_reuse_evaluation.md` (the per-module reuse audit). That document established *what can be reused*; this one defines *what the clone actually is*: a lean real-time station simulation engine whose only mandatory outputs are **OPC UA (TCP)**, **OPC UA PubSub over MQTT**, and **SparkplugB**, controlled through a **REST interface**, with all historian/analytics/observability machinery moved to separate optional packages.

---

## 1. Design Rule

> The core engine must run, publish, and be controllable with **zero** analytic dependencies installed. Everything that stores, charts, or analyzes data is a plugin the core does not know about at import time.

Consequences:

- No `influxdb-client`, `neo4j`, `pandas`, `scikit-learn`, or Telegraf/Grafana anywhere in the core dependency set.
- Core deps only: `pyyaml`, `ruamel.yaml`, `opcua`, `paho-mqtt`, `scipy` (distribution sampling), `flask` (REST), `numpy`.
- Optional capability = optional package = compose profile = UI checkbox. One switch per concern, consistent across all three layers.

---

## 2. Core vs Optional Split

### Core (always installed, always importable)

| Component | Source in parent | Notes |
|---|---|---|
| `station_engine.py` | New (Tier 4 of the reuse evaluation) | Fixed-timestep state machines, buffers as counters, health/repair model |
| `process_values.py` | New (Tier 5) | Per-station float signals (temperature/force/distance), profiles + DistributionFactory noise |
| `alarms.py` | New (Tier 5) | Reason-coded alarm registry (`FM_*`, `PV_*`, `CS_*`), replaces boolean flatten layer |
| `config_loader.py` | Carry over | Extend schema: `process_values:`, `alarm reasons`, `comms:` |
| `failure_modes.py` | Carry over unchanged | `DistributionFactory` + `FailureModeManager` |
| `recipe_runner.py` | Carry over, 2-import swap | Recipe parse/overrides/changeovers unchanged |
| `line_state.py` | Carry over, 6-line adapter | Isolation shim between engine and publishers |
| `opcua_nodes.py`, `kpi.py` | Extracted from parent `opcua_server.py` | Node builders, `CachedOpcuaNode`, OEE calc — already simantha-free |
| Publisher layer (`publishers/`) | See §3 | OPC UA TCP, OPC UA-over-MQTT, SparkplugB behind one ABC |
| REST API (`rest_api.py`) | See §4 | Embedded in the engine process |
| Simplified web UI | Slimmed from parent `docker/webui/` | See §5 |

**Kept in core but feature-flagged in config (no extra deps):** `shift_manager.py`, `spc_analytics.py` (numpy-only; feeds quality alarms — but its UI/charting stays in the analysis plugin), `fault_injector.py`.

### Optional plugins (separate installable extras, lazy-registered)

| Plugin | Contents from parent | Extra deps |
|---|---|---|
| `historian-csv` | `CSVHistorian` from `event_historian.py` | none (stdlib) — still optional so the core has no file-writing side effects by default |
| `historian-influx` | `InfluxDBHistorian` + Telegraf generator + Grafana provisioning | `influxdb-client` |
| `historian-neo4j` | `neo4j_historian.py` + NeoDash assets | `neo4j` |
| `analysis` | `report_engine.py`, `analyze_historian.py`, reports/runs/validation UI pages | `pandas` |
| `anomaly` | `experiment/detect_anomalies.py` lineage | `scikit-learn`, `pandas` |

The `SimEvent` dataclass and the `EventHistorian` ABC (both dependency-free) stay in core as the **contract**; concrete backends live in the plugins. This is the pattern the parent already uses (lazy imports in `event_historian.py`) — the clone promotes it from lazy-import-inside-one-file to actual package separation.

### Plugin mechanism (keep it boring)

No entry-point framework needed initially. A registry dict + guarded imports, driven by config:

```python
# core/plugins.py
HISTORIAN_BACKENDS = {}   # name -> factory, populated by optional packages

def load_configured_plugins(config):
    for name in config.get("historians", []):
        try:
            module = importlib.import_module(f"simengine_{name}")
            module.register(HISTORIAN_BACKENDS)
        except ImportError as e:
            raise RuntimeError(
                f"historian '{name}' configured but package not installed: "
                f"pip install simengine[{name}]") from e
```

Packaging: single repo, `pyproject.toml` with extras — `pip install simengine[historian-influx,analysis]`. Splitting into separate repos is not warranted at this scale.

---

## 3. Comms Stack (the core's entire output surface)

One abstraction, three implementations, all selectable independently:

```python
class StatePublisher(ABC):
    def on_run_start(self, snapshot): ...   # birth messages / address-space ready
    def publish(self, snapshot): ...        # once per engine step (or per publish_interval)
    def on_run_end(self): ...               # death messages / cleanup
    def close(self): ...
```

| Publisher | Transport | Payload | Source |
|---|---|---|---|
| `OPCUAServerPublisher` | OPC UA TCP :4840 | ISA-95 address space (parent's node builders, `CachedOpcuaNode` dead-bands, batched writes) | Extracted from parent |
| `OPCUAMqttPublisher` | MQTT | Part 14 JSON NetworkMessages on `opcua/{publisher_id}/json`; optional flat `simengine/{line}/{station}/{metric}` topics | Parent's `mqtt_publisher.py`, carried over |
| `SparkplugBPublisher` | MQTT | Protobuf NBIRTH/DBIRTH/NDATA/DDATA on `spBv1.0/{group}/{type}/{edge_node}/{device}`; metric aliases; delta publishing (only changed metrics per DDATA) | New — `tahu`/`sparkplug-b` dep, optional install but core-eligible |
| `CompositePublisher` | — | Fan-out to all enabled publishers | Trivial |

SparkplugB mapping: `group_id` = area, `edge_node_id` = line, `device_id` = station. Process values, states, health, alarm reason codes all become Sparkplug metrics with datatypes declared in DBIRTH. NDEATH via MQTT Will gives consumers (Ignition, HiveMQ, Optix via broker) stale-data detection for free.

Config block (single source of truth; REST/UI write it):

```yaml
comms:
  opcua:
    enabled: true          # the default; Optix's primary path
    port: 4840
  opcua_mqtt:
    enabled: false
    broker: "mqtt://mosquitto:1883"
    publisher_id: "simengine-line1"
    flat_topics: true
    publish_interval: 1
  sparkplugb:
    enabled: false
    broker: "mqtt://mosquitto:1883"
    group_id: "Area01"
    edge_node_id: "Line1"
```

All three publishers consume the same per-step `snapshot` (built once from `LineState` + station states + process values + alarm registry). Adding a fourth protocol later = one class.

### 3.1 Broker: Mosquitto serves both MQTT protocols — no second broker needed

SparkplugB is not a broker feature. It is a payload-and-topic convention layered on standard MQTT 3.1.1: Protobuf payloads on `spBv1.0/...` topics, QoS 0/1, an MQTT Will for NDEATH, non-retained messages. Every compliant broker carries it, and **Eclipse Mosquitto 2.x satisfies all of it**. The single Mosquitto instance in the core compose therefore serves plain MQTT, OPC UA PubSub JSON, and SparkplugB simultaneously.

One nuance, documented so it never surprises anyone: Sparkplug 3.0 defines an optional **"Sparkplug Aware" broker profile** — the broker itself retains birth certificates under `$sparkplug/certificates/#` so late-joining consumers can recover metric definitions without waiting for a rebirth. Mosquitto does not implement this profile (HiveMQ does, via extension). It is not needed here:

- Sparkplug consumers (Ignition, HiveMQ clients, Optix via broker) handle non-aware brokers by issuing a **Node Control/Rebirth** command, which our `SparkplugBPublisher` must implement (subscribe to `spBv1.0/{group}/NCMD/{edge_node}`, re-emit NBIRTH/DBIRTH on request). This is a mandatory part of the Sparkplug spec for edge nodes anyway, not extra work.
- In a simulation context, runs are short-lived and every run start emits fresh births.

Decision: **keep Mosquitto as the only broker.** Revisit only if a Sparkplug-Aware requirement materializes from a specific consumer — and even then, the swap is a compose image change, not a code change.

### 3.2 Differentiating OPC UA-over-MQTT and SparkplugB output

Both publishers carry the same underlying metrics (same snapshot), so the streams must be unmistakably distinguishable on the wire. They are — on four independent axes, and the spec makes each explicit so the two can coexist on one broker without any consumer ambiguity:

| Axis | OPC UA PubSub over MQTT | SparkplugB |
|---|---|---|
| **Topic root** (primary differentiator) | `opcua/{publisher_id}/json` (+ optional flat `simengine/{line}/...`) | `spBv1.0/{group_id}/{msg_type}/{edge_node_id}[/{device_id}]` |
| **Encoding** | UTF-8 JSON (Part 14 NetworkMessage envelope: `MessageType: "ua-data"`) | Protobuf (Sparkplug B payload schema) |
| **MQTT 5 `Content-Type` property** | `application/json+opcua` | not set (Sparkplug mandates MQTT 3.1.1 semantics; the `spBv1.0/` prefix is its own discriminator) |
| **Session identity** | client id `simengine-uapubsub-{publisher_id}`; `PublisherId` field inside every message | client id `simengine-spb-{edge_node_id}`; bdSeq/seq numbers + NBIRTH lifecycle |

Rules that follow:
- The topic namespaces are disjoint by construction — a subscriber to `spBv1.0/#` can never receive a Part 14 JSON message and vice versa. No shared topic is ever used by both publishers.
- Each publisher maintains its **own MQTT client connection** (distinct client ids, distinct Will messages: Part 14 status topic `opcua/{publisher_id}/status` → `"OFFLINE"` vs Sparkplug NDEATH). One protocol disconnecting must not tear down the other.
- Metric **names** are kept identical across both encodings (`{Station}.{Metric}`, e.g. `Press01.OilTemp`) so a consumer switching protocols maps data 1:1 — the differentiation is transport/encoding, deliberately *not* the data model.
- The Comms UI page shows the live topic root next to each enabled checkbox, so what-goes-where is visible at a glance.

---

## 4. REST Interface

Embedded in the engine process (Flask thread, same dep the project already uses) — **not** the parent's model of a separate web app reading back through an OPC UA client. Direct in-process state access removes ~400 OPC UA round-trips per poll and makes the API authoritative.

```
GET  /api/v1/state                      # full snapshot: line KPIs, per-station state/health/PVs/alarms
GET  /api/v1/state/stations/{name}      # one station
GET  /api/v1/runs/current               # run_id, scenario, sim_time, stop conditions, status
POST /api/v1/runs                       # {scenario, seed?, speed_ratio?} -> 201 {run_id}
POST /api/v1/runs/recipe                # {recipe, seed?} -> 201 {run_id}
DELETE /api/v1/runs/current             # stop the running simulation

GET  /api/v1/scenarios                  # list
GET/PUT /api/v1/scenarios/{name}        # read / replace (validated by config_loader)
POST /api/v1/scenarios                  # create

GET  /api/v1/recipes                    # list
GET/PUT /api/v1/recipes/{name}          # read / replace (validated by recipe_runner validators)
POST /api/v1/recipes                    # create

GET/PUT /api/v1/comms                   # read / update the comms block (applies on next run)
GET  /healthz                           # liveness for compose/k8s
```

Rules:
- All mutating config endpoints reuse the existing validators (`validate_serial_topology`, `validate_recipe`, new `validate_comms_config`) — REST is a thin transport over logic that already exists.
- Comms changes apply at next run start (publishers are constructed per run); the response says so explicitly.
- `GET /api/v1/state` reads the same snapshot object the publishers consume — one representation, no drift between REST and OPC UA values.
- Parent endpoints that move to the `analysis` plugin: `/api/reports/*`, `/api/runs` history, `/api/validation/*`, `/api/historian/*`. The plugin registers its own Flask blueprints when installed.

---

## 5. Simplified UI

Strip the parent's six-page app to three, served by the same embedded Flask:

| Page | Content |
|---|---|
| **Dashboard** | Line state, per-station state/health/current alarm reason, live process-value readouts. Polls `GET /api/v1/state` (one cheap in-process call — no OPC UA client, no M1–M19 scan). |
| **Configure** | Scenario editor (reuse parent's config.html CRUD skeleton) + recipe editor. |
| **Comms** | Checkbox per publisher — ☐ OPC UA · ☐ OPC UA over MQTT (+ broker, flat topics) · ☐ SparkplugB (+ broker, group/edge IDs) — plus detected optional plugins shown as installed/not-installed (historians, analysis). Writes `PUT /api/v1/comms`. |
| Start/stop + run status | Header bar on all pages (scenario picker, seed, speed ratio, run_id). |

Removed from core UI (available again when the `analysis` plugin is installed, which registers its pages): reports, run history/comparison, pipeline validation, embedded docs, deep SPC charting.

---

## 6. Deployment Shape

- **Core compose:** `simengine` (engine + REST/UI, ports 8080 + 4840) and `mosquitto` (only started when an MQTT-based publisher is enabled). Two containers.
- **Optional profiles** (matching the plugin split): `--profile influx` → influxdb + telegraf + grafana; `--profile graph` → neo4j + neodash; `--profile monitoring` → prometheus + cadvisor + node-exporter.
- Docker image installs core extras only; plugin extras via build arg (`--build-arg EXTRAS=historian-influx,analysis`).
- The parent's performance spec items (batched OPC UA writes, requirements split, multi-stage Dockerfile) apply directly to the clone and should be built in from day one rather than retrofitted.

---

## 7. Changes to the Reuse Evaluation Tiers

This scope refinement moves several items relative to `clone_reuse_evaluation.md`:

| Item | Was | Now |
|---|---|---|
| `event_historian.py` backends | Tier 1 core carry-over | ABC + `SimEvent` stay core; CSV/Influx backends → optional plugins |
| `neo4j_historian.py` | Tier 1 core carry-over | `historian-neo4j` plugin |
| Telegraf generator, Grafana assets, InfluxDB service | Tier 1 core carry-over | `historian-influx` plugin + compose profile |
| `tools/report_engine.py`, `analyze_historian.py`, reports/runs/validation UI | Tier 1 core carry-over | `analysis` plugin (pandas) |
| scikit-learn / anomaly experiment | (out of image already) | `anomaly` plugin |
| `spc_analytics.py` | Tier 1 core | Core module (numpy-only), feature-flagged; charting UI → `analysis` plugin |
| Parent web UI (6 pages, OPC UA client polling) | Tier 1 carry-over | Slimmed to 3 pages on embedded REST; OPC UA client reader dropped entirely |
| SparkplugB | Not in parent | Core-eligible publisher (optional dep) |
| REST API | Partial (parent's subprocess-manager Flask app) | First-class, embedded, authoritative |

Unchanged: everything in Tiers 3–5 (subclass logic salvage, `station_engine.py`, process values, reason-coded alarms, cycle stops) and the recommendation to drop Simantha entirely.

---

## 8. Build Order

1. Repo skeleton + `pyproject.toml` with extras; carry over Tier-1 core modules (`config_loader`, `failure_modes`, `line_state`, `recipe_runner`, extracted `opcua_nodes`/`kpi`).
2. `station_engine.py` + process values + reason-coded alarms (the engine identity).
3. Publisher ABC + `OPCUAServerPublisher` (Optix works end-to-end here).
4. Embedded REST API + 3-page UI (engine is now controllable).
5. `OPCUAMqttPublisher` (carry over) + `SparkplugBPublisher` (new) + comms checkboxes.
6. Plugin registry + `historian-csv`/`historian-influx` plugins + compose profiles.
7. `analysis` plugin re-hosting the parent's reporting when needed.

Steps 1–4 produce a usable product; 5–7 are additive.
