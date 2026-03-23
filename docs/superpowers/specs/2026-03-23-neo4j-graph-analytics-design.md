# Neo4j Graph Analytics Integration — Design Spec

**Date:** 2026-03-23
**Status:** Approved
**Scope:** Real-time Neo4j ingestion, causal inference, NeoDash dashboards, Flask Graph tab

---

## 1. Goal

Demonstrate the unique analytical value of a graph database alongside InfluxDB by:
- Ingesting manufacturing simulation events into Neo4j in real time
- Automatically inferring causal relationships between machine events (failure cascades, starvation propagation, SPC → quality impact)
- Providing two visualisation surfaces: NeoDash (open-ended Cypher exploration) and embedded Flask panels (operational insights)

---

## 2. Architecture Overview

```
opcua_server.py
  └── CompositeHistorian
        ├── CSVHistorian          (unchanged)
        ├── InfluxDBHistorian     (unchanged)
        └── Neo4jHistorian        (complete rewrite)
              ├── Batch UNWIND writes (50-event batches)
              ├── Run/Shift node management
              └── Causal inference engine (in-process, sliding window)

Docker stack additions:
  neo4j:5-community   (ports 7474, 7687)  + APOC plugin
  neo4j/neodash       (port 5005)

Flask Web UI addition:
  /graph page  +  /api/graph/causal  /api/graph/topology  /api/graph/compare
  Rendered with vis.js network graphs
```

---

## 3. Graph Schema

### Node Types

| Label | Key Properties | Description |
|-------|---------------|-------------|
| `:Run` | `run_id`, `scenario`, `seed`, `start_wall_clock` | One per simulation run |
| `:Shift` | `number`, `name`, `start_time`, `end_time`, `oee` | One per shift boundary |
| `:Machine` | `name`, `cycle_time`, `p_degrade`, `h_max`, `scenario` | Static per run |
| `:Buffer` | `name`, `capacity`, `scenario` | Static per run |
| `:Event` | `type`, `sim_time`, `old_state`, `new_state`, `oee`, `utilisation`, `severity`, `run_id` | One per historian event |

### Relationships

| Relationship | From → To | Properties | How Created |
|---|---|---|---|
| `:FEEDS` | Machine/Buffer → Buffer/Machine | — | `create_topology()` at run start |
| `:INCLUDES` | Run → Machine/Buffer | — | At topology creation |
| `:HAD_SHIFT` | Run → Shift | — | On SHIFT_CHANGE event |
| `:HAD_EVENT` | Machine/Buffer → Event | `sim_time` | Per event write |
| `:OCCURRED_IN` | Event → Shift | — | Per event write |
| `:FOLLOWED_BY` | Event → Event (same machine) | `gap_s` | Per event write (linked list per machine) |
| `:CAUSED` | Event → Event (cross machine) | `type`, `lag_s` | Causal inference engine |

### Causal Inference Rules

All rules use a sliding in-memory window of recent events per machine (kept in `Neo4jHistorian`). Topology adjacency (upstream/downstream machine names) is loaded at run start from config.

| Rule | Trigger | Target | Window | Edge type |
|------|---------|--------|--------|-----------|
| Failure → starvation cascade | Mn enters FAILED or UNDER_REPAIR | Mn+1 enters STARVED | 5s | `starvation_cascade` |
| Blocking cascade | Mn enters BLOCKED | Mn-1 enters BLOCKED | 5s | `blocking_cascade` |
| SPC → quality impact | SPC_VIOLATION on Mn | SCRAP or REWORK on Mn | 30s | `spc_quality_impact` |
| Repair → recovery | Mn exits UNDER_REPAIR | Mn+1 exits STARVED | 10s | `repair_recovery` |

**Window boundary semantics:** `lag_s = target.sim_time - trigger.sim_time`. A CAUSED edge is written if `0 < lag_s <= window` (strictly positive — same-timestep events are not causal). If multiple trigger events exist within the window for the same target, only the most recent trigger creates a CAUSED edge. The `type` property value is the exact snake_case string from the table above and is directly queryable in Cypher.

**Concrete example:**
```
M2 enters UNDER_REPAIR at sim_time=100.0
M3 enters STARVED     at sim_time=104.8  → lag_s=4.8 ≤ 5.0 → CREATE [:CAUSED {type:"starvation_cascade", lag_s:4.8}]
M3 enters STARVED     at sim_time=105.2  → lag_s=5.2 > 5.0 → no edge
```

---

## 4. Neo4jHistorian Rewrite

The existing `src/neo4j_historian.py` is a placeholder with no causal logic, per-event round-trip writes, and no Run/Shift nodes. It is **replaced entirely**.

### Key design decisions

**Batch writes:** Events are accumulated in a buffer (size 50) and written using Cypher `UNWIND` — one round-trip per batch instead of one per event. This reduces Neo4j write overhead ~50x.

**Causal inference in-process:** `_causal_engine` maintains `recent_events: dict[machine_name, deque]` (max 100 entries, sliding window). On each STATE_CHANGE flush, it checks neighbouring machines and writes `:CAUSED` edges in the same batch transaction.

**Topology adjacency map:** Built from config at `create_topology()` time — `_upstream: dict[str, str]` and `_downstream: dict[str, str]`. Used by the causal engine to know which machines to check.

**Run node lifecycle:** Created on first `record_events()` call for a new `run_id`. `end_time` updated on `close()`.

**Shift tracking:** `_current_shift` tracked in memory; new `:Shift` node created and linked to `:Run` on each SHIFT_CHANGE event.

**FOLLOWED_BY chain:** `_last_event_id: dict[machine_name, int]` tracks the Neo4j internal ID of the most recent event per machine. Each new event for that machine gets a `:FOLLOWED_BY` edge from the previous one.

### Integration with CompositeHistorian

`Neo4jHistorian` is **kept separate** from `CompositeHistorian` — it is instantiated alongside it in `opcua_server.py` and called explicitly:

```python
historian = CompositeHistorian([csv_hist, influx_hist])   # unchanged
neo4j_hist = Neo4jHistorian(...)                          # separate
# in main loop:
historian.record_events(events)
if neo4j_hist:
    neo4j_hist.record_events(events)                      # own batching
```

This avoids batch-size conflicts with CSV's immediate flush semantics. The `CompositeHistorian` interface is not changed.

### Error handling

- **Connection failure at init:** raises `ConnectionError` with a clear message; simulation startup halts and logs the error. Neo4j is optional — if `neo4j:` is not in the historian config, the historian is not created and no error occurs.
- **Mid-run write failure:** `record_events()` catches all Neo4j exceptions, logs a WARNING, discards the failed batch, and continues. The simulation is never interrupted by Neo4j unavailability.
- **Causal inference failure:** errors in `_causal_engine` are caught separately and logged; the event write still completes. A causal edge is skipped rather than blocking the batch.
- **Hang/timeout:** Neo4j driver is configured with `connection_timeout=5s`, `max_transaction_retry_time=10s`.

### Public interface (unchanged from existing)

```python
Neo4jHistorian(uri, user, password, scenario_name, run_id)
.create_topology(config)        # called once at run start
.record_events(events)          # called every sim step
.flush()                        # force-write buffer
.close()                        # flush + set Run.end_time
.describe() -> str
```

`record_parts()` is removed (out of scope for this phase — see §8).

---

## 5. Docker Stack Changes

### New services in `docker/docker-compose.yml`

```yaml
neo4j:
  image: neo4j:5-community
  ports: ["7474:7474", "7687:7687"]
  environment:
    NEO4J_AUTH: ${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-simantha}
    NEO4J_PLUGINS: '["apoc"]'
    NEO4J_dbms_security_procedures_unrestricted: apoc.*
  volumes:
    - ./neo4j/data:/data
    - ./neo4j/logs:/logs

neodash:
  image: neo4j/neodash:latest
  ports: ["5005:5005"]
  depends_on: [neo4j]
```

### New files

- `docker/neo4j/data/` — gitignored, holds Neo4j data volume
- `docker/neo4j/dashboards/manufacturing_causal.json` — NeoDash dashboard definition (committed)
- `.env` additions: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`

### APOC requirement

APOC is needed for `apoc.path.spanningTree()` used in the causal chain Flask query. It is loaded via the `NEO4J_PLUGINS` environment variable — no manual plugin installation required with Neo4j 5.

---

## 6. NeoDash Dashboards

Five pre-built NeoDash dashboards stored as a JSON definition committed to `docker/neo4j/dashboards/manufacturing_causal.json` and seeded into Neo4j on first startup via an init script.

**Seeding mechanism:** A `docker/neo4j/seed-dashboards.sh` script runs as part of `docker compose up` using a one-shot init container or the Neo4j `docker-entrypoint-initdb.d/` hook. It checks for an existing `_Neodash_Dashboard` node and skips if already present:

```cypher
// seed-dashboards.cypher
MERGE (d:_Neodash_Dashboard {title: "Manufacturing Causal Analysis"})
ON CREATE SET d.content = $dashboard_json, d.date = datetime()
```

The dashboard JSON (`manufacturing_causal.json`) uses NeoDash 3.x format and is created during development via the NeoDash UI then exported and committed. Graph analytics are Flask/NeoDash only — no OPC UA variables are added for graph-derived metrics in this phase.

| Dashboard | Key Cypher pattern | Purpose |
|---|---|---|
| Causal Chain Explorer | `MATCH path=(e1:Event)-[:CAUSED*1..6]->(e2:Event)` | Browse any causal chain interactively |
| Failure Pattern Finder | `MATCH (m:Machine)-[:HAD_EVENT]->(e:Event {new_state:'UNDER_REPAIR'})` grouped | Which machines fail most, in which shifts |
| SPC → Quality Impact | `MATCH (e1)-[:CAUSED {type:'spc_quality_impact'}]->(e2)` | SPC violation to scrap/rework chains |
| Shift Breakdown | `MATCH (r:Run)-[:HAD_SHIFT]->(s:Shift)<-[:OCCURRED_IN]-(e:Event)` | Events and OEE per shift |
| Cross-Run Comparison | `MATCH (r:Run) WITH r, size((r)-[:INCLUDES]->()) as machines` | Structural stats across runs |

---

## 7. Flask Graph Tab

### New route: `/graph`

New tab in the Flask web UI nav bar. Renders `templates/graph.html` with three vis.js panels.

### API endpoints

| Endpoint | Cypher query | Returns |
|---|---|---|
| `GET /api/graph/causal?run_id=X` | Traverse `:CAUSED` from most recent UNDER_REPAIR event, up to 8 hops | `{nodes: [...], edges: [...]}` for vis.js |
| `GET /api/graph/topology?run_id=X` | Full topology + latest state per machine from last Event | `{nodes: [...], edges: [...]}` with state colours |
| `GET /api/graph/compare?run_a=X&run_b=Y` | Aggregate CAUSED edge counts, cascade depth, repair frequency per run | `{run_a: {...}, run_b: {...}}` |

### Panel A — Live Causal Chain

- vis.js Network graph
- Node colours: machine state colour coding (green/red/orange/purple)
- Auto-refreshes every 5s while a simulation is running
- Shows the single deepest causal chain from the most recent failure event

### Panel B — Topology Health Map

- Full line rendered as left-to-right network (Source → M1 → B1 → … → Sink)
- Node colour = current machine state (from last `:Event` on that machine)
- Click a machine node → side panel shows last 5 events as a table
- Static during post-run review; live during run

### Panel E — Cross-Run Comparison

- Run selector dropdowns (populated from `GET /api/runs`)
- Side-by-side stat cards: total CAUSED edges, average cascade depth (hops), most-connected failure node, mean repair recovery time
- Highlights which run produced more disruptive failure patterns

---

## 8. Scenario Config — Neo4j Toggle

The web UI config editor (`/config`) adds a **"Neo4j Historian"** checkbox for the `full_feature_8_machine_line` and `full_feature_8_machine_line_rtf` scenarios. When enabled, it inserts the `neo4j` historian block into the scenario YAML:

```yaml
historian:
  csv:
    output_dir: results/historian
    rotate_on_shift: true
  neo4j:
    uri: ${NEO4J_URI}
    user: ${NEO4J_USER}
    password: ${NEO4J_PASSWORD}
```

The checkbox only appears in the config editor when the scenario already has a `historian:` key. It is off by default — existing scenarios are unaffected. When toggled on, the full `neo4j:` block (with environment variable substitution) is auto-inserted into the scenario YAML. When toggled off, the `neo4j:` key is removed. The checkbox state is derived from the presence/absence of the `neo4j:` key in the current scenario config.

---

## 9. Future Extensions (Out of Scope for This Phase)

The following were identified as valuable but excluded to keep scope manageable. They should be considered for a follow-on phase:

- **Part-level traceability** — individual `:Part` nodes linked to machines via `:PROCESSED_BY`, tracking each part's journey through the line including rework attempts. Requires per-part identifiers in the simulation.
- **Neo4j Bloom** — richer graph exploration UI with saved perspectives and visual query building. Requires Neo4j Enterprise or AuraDB (paid). Alternative to NeoDash for non-technical users.
- **Grafana → Neo4j panels** — community Grafana plugin (`halin` or `neo4j-datasource`) to surface Cypher query results in Grafana dashboards alongside InfluxDB panels. Useful for unified dashboard experience.
- **Anomaly pattern library** — store known failure signatures as subgraph templates, then query new runs for structural similarity. Enables proactive alerting: "this run is exhibiting the M2-degrades → M3-starves pattern that preceded last month's quality escape."
- **Multi-line topology** — extend the graph schema to support converging/diverging topologies (multiple parallel lines feeding a shared assembly stage).

---

## 10. Implementation Sequence

1. Docker stack — add Neo4j + NeoDash services, `.env` keys, `docker/neo4j/` directory
2. Neo4jHistorian rewrite — complete replacement of `src/neo4j_historian.py`
3. Tests — unit tests for causal inference engine and batch write logic
4. NeoDash dashboard definition — JSON file + seeding script
5. Flask `/graph` tab — route, template, three API endpoints, vis.js panels
6. Config editor Neo4j toggle — checkbox in `/config` for 8-machine scenarios
7. README update — future extensions section, Neo4j setup instructions
8. Update `full_feature_8_machine_line` scenario YAML to include commented-out neo4j historian block as reference

---

## 11. Dependencies

| Package | Where used | Already installed |
|---|---|---|
| `neo4j>=5.0.0` | `Neo4jHistorian` | No — lazy import, optional |
| `vis.js` (CDN) | Flask graph panels | No — loaded from CDN |
| Neo4j APOC plugin | causal chain queries | No — auto-loaded via Docker env var |
