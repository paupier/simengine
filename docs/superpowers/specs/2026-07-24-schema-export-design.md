# Schema Export (OPC UA / MQTT / SparkplugB) — Design

## Problem

Integrators wiring simengine into SCADA/MES tools (Optix, Ignition, UaExpert)
currently have to either start a run and browse the live OPC UA server / MQTT
broker, or read the publisher source to know what tags/topics/metrics a given
scenario will produce. There's no way to see — or export — the exact wire
schema for a scenario's configured protocols without a live run.

The knowledge graph (`GET /api/v1/kg`) already binds every metric to its wire
addresses, but it's a curated semantic subset for the AI interface (nodes are
process values / failure modes / alarm codes / metrics, not a literal
address-space tree), and it requires an active run (`run_manager.knowledge_graph`
is built at run start). This feature is a different, complementary view: the
literal structure a client would see on the wire, buildable from a saved
scenario config alone.

## Scope

- `GET /api/v1/schema?scenario=<name>` — builds and returns the OPC UA, MQTT
  (Part 14 JSON + flat topics), and SparkplugB schema for a saved scenario's
  config + comms block. No run required.
- A new "Schema" section in the Comms tab: a "View schema" button renders the
  three protocol schemas as formatted, copyable JSON, plus a "Download JSON"
  button for the whole document.

## Non-goals

- Not a draft/preview-from-unsaved-config endpoint (unlike `/api/v1/kg/preview`)
  — the Comms tab already operates on saved scenarios; this mirrors that.
- Not a replacement for `/api/v1/kg` — the KG stays the AI-facing semantic
  model; this is the literal wire-format view for integrators.
- Not wired into the MCP tool registry — a REST/UI feature only, at least
  for v1.
- No OPC UA server actually started, no MQTT/SparkplugB broker connection
  made — purely address-space/metric-name construction in memory.

## Architecture

**Refactor (behavior-preserving):**

- `publishers/metrics.py`: extract the static (name, datatype) pairs
  currently inlined in `station_metrics()`/`line_metrics()` into
  `STATION_METRIC_SCHEMA` / `LINE_METRIC_SCHEMA` module-level tuples. Add
  two pure, config-only functions:
  - `station_metric_schema(pv_names: list[str]) -> list[tuple[str, str]]`
  - `line_metric_schema(buffer_names: list[str]) -> list[tuple[str, str]]`
  `station_metrics()`/`line_metrics()` are refactored to build their dict
  from these same constants plus live values, so there is exactly one
  source of truth for "what metrics exist and in what order" — the runtime
  encoders and the schema exporter cannot drift apart.

- `publishers/opcua_server.py`: extract the address-space construction out
  of `OPCUAServerPublisher._build(self, snapshot)` into a module-level
  `build_address_space(config: dict, port: int, run_id: str = "",
  speed_ratio: float = 1.0) -> tuple[Server, dict]`. `_build` becomes a
  thin wrapper calling this with `snapshot.run_id`/`snapshot.speed_ratio`.
  `opcua.Server()` builds its address space entirely in memory and spawns
  no threads/sockets until `.start()` is called (verified: `threading.active_count()`
  unchanged after building a full tree), so the schema exporter can call
  `build_address_space()` directly with placeholder `run_id`/`speed_ratio`
  and never start a server — it builds the *real* node tree via the *real*
  builder functions (`opcua_nodes.py`), then discards it.

**New module `src/simengine/api/schema.py`** (no engine/run coupling, like
`api/diagnostics.py`):

- `build_opcua_schema(config: dict, port: int) -> dict` — calls
  `build_address_space(config, port)`, then recursively walks the tree from
  `get_objects_node()` via `get_children()` / `get_browse_name()` /
  `get_node_class()` / `get_data_type_as_variant_type()` (for variables),
  producing a nested JSON tree of `{name, node_id, node_class, data_type?,
  children?}`. Server is discarded after the walk (never started, nothing to
  close).

- `build_mqtt_schema(config: dict, mqtt_cfg: dict) -> dict` — using
  `line_metric_schema`/`station_metric_schema`, builds:
  - Part 14 JSON: `data_topic`, `status_topic`, `publish_interval`, and an
    `envelope` shape whose `Payload` keys are exactly what
    `OPCUAMqttPublisher.publish()` writes (`f"{name}.{metric.replace('/', '.')}"`
    for stations, `f"Line.{metric...}"` for line metrics), mapped to
    datatype names.
  - `flat_topics`: one entry per station metric — `{topic, payload: {value:
    <datatype>, sim_time: "Float", run_id: "String"}}` — using the real
    `flat_topic()` helper from `opcua_mqtt.py` (already the single source of
    truth for flat topic strings; also used by the knowledge graph).

- `build_sparkplugb_schema(config: dict, spb_cfg: dict) -> dict` — replicates
  `SparkplugBPublisher._publish_births()`'s exact registration order (line
  metrics first — including the unaliased `bdSeq` / `Node Control/Rebirth`
  node metrics — then per station in config order, each station's metrics in
  `station_metric_schema` order) to assign the same alias numbers a real run
  would assign, without touching protobuf or a broker connection. Returns
  `nbirth_topic`/`ndata_topic`/`ndeath_topic`/`ncmd_topic`, `node_metrics:
  [{name, alias, datatype}]`, and `devices: [{station, dbirth_topic,
  ddata_topic, ddeath_topic, metrics: [...]}]`.

None of these three builders require the `sparkplug` extra (protobuf) — only
*runtime* SparkplugB publishing does; the schema is just name/alias/datatype
bookkeeping.

## API

`GET /api/v1/schema?scenario=<name>`

- Loads the scenario config the same way `GET /api/v1/comms` does (existing
  loader), 404 if the scenario doesn't exist.
- Reads the scenario's `comms` block for per-protocol settings (port,
  broker, publisher_id, group_id, edge_node_id), falling back to the same
  defaults the Comms tab UI shows (4840, `mqtt://mosquitto:1883`,
  `simengine-line1`, `Area01`, `Line1`) when a protocol isn't configured.
- **All three sections are always computed**, regardless of each protocol's
  `enabled` flag — you can preview a protocol's shape before turning it on.
  Each section carries `"enabled": <bool>` from the comms config.

Response shape:

```json
{
  "scenario": "demo_line",
  "opcua": {
    "enabled": true,
    "endpoint": "opc.tcp://<host>:4840/simengine/",
    "namespace_uri": "http://simengine.local/",
    "address_space": { "name": "Objects", "node_class": "Object", "children": [ ... ] }
  },
  "mqtt": {
    "enabled": true,
    "part14": {
      "data_topic": "opcua/simengine-line1/json",
      "status_topic": "opcua/simengine-line1/status",
      "publish_interval": 1,
      "envelope": {
        "MessageId": "String", "MessageType": "String", "PublisherId": "String",
        "DataSetWriterId": "Int32", "Timestamp": "String",
        "Payload": { "Line.SimTime": "Float", "Station1.State": "String", "...": "..." }
      }
    },
    "flat_topics": [
      { "topic": "simengine/Line1/Station1/state",
        "payload": { "value": "String", "sim_time": "Float", "run_id": "String" } }
    ]
  },
  "sparkplugb": {
    "enabled": false,
    "group_id": "Area01", "edge_node_id": "Line1",
    "nbirth_topic": "spBv1.0/Area01/NBIRTH/Line1",
    "ndata_topic": "spBv1.0/Area01/NDATA/Line1",
    "ndeath_topic": "spBv1.0/Area01/NDEATH/Line1",
    "ncmd_topic": "spBv1.0/Area01/NCMD/Line1",
    "node_metrics": [
      { "name": "bdSeq", "alias": null, "datatype": "UInt64" },
      { "name": "Node Control/Rebirth", "alias": null, "datatype": "Boolean" },
      { "name": "SimTime", "alias": 1, "datatype": "Float" }
    ],
    "devices": [
      { "station": "Station1",
        "dbirth_topic": "spBv1.0/Area01/DBIRTH/Line1/Station1",
        "ddata_topic": "spBv1.0/Area01/DDATA/Line1/Station1",
        "ddeath_topic": "spBv1.0/Area01/DDEATH/Line1/Station1",
        "metrics": [ { "name": "State", "alias": 8, "datatype": "String" } ] }
    ]
  }
}
```

## UI

`comms.html`: new "Schema" section below the existing protocol grid.

- "View schema" button → `GET /api/v1/schema?scenario=<selected>`, renders
  three collapsible panels (OPC UA / MQTT / SparkplugB), each a `<pre
  class="mono">` block with `JSON.stringify(section, null, 2)` and its own
  "Copy" button (`navigator.clipboard.writeText`) — plain-text copy/paste,
  no interactive tree widget (YAGNI; the KG page already has a graph view
  for exploratory browsing, this is for pasting into a client's config).
- One "Download JSON" button for the full response — client-side `Blob` +
  `<a download>`, no server-side format parameter needed.
- Re-fetches automatically when the header scenario picker changes, same
  pattern as `loadComms()`.

## Error handling

- Unknown scenario → 404 `{"error": "..."}", same convention as `GET /api/v1/comms`.
- Malformed config (missing required keys) → the existing config loader's
  validation already rejects this at save time; `/api/v1/schema` assumes a
  previously-validated saved scenario and lets `KeyError`/`TypeError`
  surface as a 400 with the exception text, consistent with
  `/api/v1/kg/preview`'s handling of a bad draft config.

## Testing

`tests/test_schema.py`:
- OPC UA: `build_opcua_schema()`'s tree contains the same node IDs
  `OPCUAServerPublisher` actually creates for a fixture scenario — build
  both (schema builder + a real, unstarted `OPCUAServerPublisher._build`)
  and diff node-id sets, proving no drift.
- MQTT: envelope `Payload` keys match what `OPCUAMqttPublisher.publish()`
  actually writes for a synthetic snapshot of the same scenario (build a
  real snapshot via the test fixtures, run one `publish()` into a captured
  payload, diff key sets against the schema's `Payload` keys). Flat topic
  strings match `flat_topic()` output exactly.
- SparkplugB: alias numbers from `build_sparkplugb_schema()` match the
  aliases `SparkplugBPublisher._publish_births()` assigns when run against
  the same config (construct the real publisher, call `_publish_births`
  with a mocked `_publish`, inspect `self._aliases`).
- Determinism: same scenario config → byte-identical schema JSON across
  repeated calls (consistent with the engine's determinism invariant
  elsewhere in the codebase).
- REST: `GET /api/v1/schema?scenario=<unknown>` → 404.

## Non-goals (recap)

Not a live-run feature, not part of the knowledge graph or MCP tool
registry, no draft/preview-from-unsaved-config variant, no server-side
export-to-file endpoint (client-side download only).
