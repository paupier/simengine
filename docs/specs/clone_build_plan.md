# Clone Build Plan — Execution-Grade Specification

**Status:** Ready for implementation
**Audience:** An AI coding agent (or developer) executing autonomously. Where this document conflicts with `clone_reuse_evaluation.md` or `clone_target_architecture.md`, **this document governs** — it exists to remove every judgment call those documents left open.
**Companion docs:** `clone_reuse_evaluation.md` (what to reuse and why), `clone_target_architecture.md` (architecture and rationale).

---

## 0. Guardrails for the Executing Agent

1. Work **phase by phase, in order**. Do not start a phase until the previous phase's Gate passes.
2. Commit at least once per numbered task, with the task ID in the commit message (e.g. `P2.3: station state machine transitions`).
3. Do **not** add any dependency not listed in §1 P0.4. If something seems missing, prefer stdlib.
4. Do **not** import `simantha` anywhere in the new repo. It is not a dependency.
5. Do **not** invent config keys. The YAML schema in §3 is exhaustive for v1; unknown keys in user files are ignored (same tolerance as the parent).
6. When a formula or state rule is given here, implement it **exactly** — these encode behavior validated in the parent project.
7. Every phase's Gate commands must run green before the phase is committed as complete.
8. All randomness must flow through `DistributionFactory` or the seeded per-step RNG (§4 P4.4). Never call unseeded `random`/`np.random` in engine code.

---

## 1. Phase 0 — Repo Bootstrap

### P0.1 Create the repo

- New repository named **`simengine`** (working title; a rename later is find-and-replace on the package name).
- Bootstrap by cloning `simantha-opcua` and re-pointing the remote (preserves useful history):

```bash
git clone <simantha-opcua-url> simengine && cd simengine
git remote remove origin   # new remote added when available
```

### P0.2 Delete (parent files that do not carry over)

```
src/opcua_server.py            # replaced by extracted modules + new engine/server
src/advanced_machine.py        # Tier 3: logic salvaged in P2, class discarded
src/quality_machine.py         # Tier 3: logic salvaged in P2, class discarded
src/priority_maintainer.py     # Tier 3: strategies salvaged in plugin era, class discarded
src/experiment_writer.py
experiment/
docs/superpowers/
docker/webui/                  # replaced by embedded REST/UI in P4
docker/telegraf/               # moves to historian-influx plugin (P6)
docker/grafana/                # moves to historian-influx plugin (P6)
docker/neo4j/                  # moves to historian-neo4j plugin (P6)
tools/                         # moves to analysis plugin (P6); keep files in git history only
tests/  (all EXCEPT the keep-list in P0.3)
config/line_models.yaml        # replaced by config/scenarios.yaml (§3)
```

Keep `src/` files not listed above; they are the Tier-1 carry-overs.

### P0.3 New layout

```
simengine/
  pyproject.toml
  src/simengine/
    __init__.py
    engine/
      __init__.py
      station.py           # P2: StationModel, state machine
      line.py              # P2: LineEngine (stations + buffers + step loop)
      process_values.py    # P3: ProcessVariable profiles
      alarms.py            # P3: AlarmRegistry, reason codes
      snapshot.py          # P1: dataclasses (the system-wide contract)
      health.py            # P2: health/degradation/repair model
    config/
      loader.py            # carried: src/config_loader.py, extended per §3
      distributions.py     # carried: src/failure_modes.py (unchanged; renamed module only)
    publishers/
      __init__.py          # StatePublisher ABC + CompositePublisher + registry
      opcua_server.py      # P4: OPC UA TCP publisher (extracted node builders)
      opcua_nodes.py       # P4: node builders + CachedOpcuaNode lifted from parent
      opcua_mqtt.py        # P5: carried from parent src/mqtt_publisher.py
      sparkplugb.py        # P5: new
    api/
      rest.py              # P4: Flask blueprint, endpoints per §6 P6.4
      ui/                  # P4: 3 templates (dashboard, configure, comms)
    runtime/
      run_manager.py       # P4: run lifecycle (start/stop/thread), run_id
      recipe_runner.py     # carried: src/recipe_runner.py, 2-import swap
      line_state.py        # carried: src/line_state.py, adapter per P4.7 counters
      shift_manager.py     # carried unchanged
      spc.py               # carried: src/spc_analytics.py unchanged
      fault_injector.py    # carried unchanged
    events/
      __init__.py          # SimEvent dataclass + EventHistorian ABC (from parent event_historian.py)
  config/
    scenarios.yaml         # §3 schema, 3 starter scenarios
    recipes/               # carried from parent
  docker/
    Dockerfile             # multi-stage, core extras only
    docker-compose.yml     # simengine + mosquitto; profiles added in P6
    mosquitto/mosquitto.conf
  tests/                   # keep-list + new per-phase tests
```

**Parent test keep-list** (they exercise carried pure modules; fix imports only): `test_failure_modes.py`, `test_distribution_validation.py`, `test_spc_analytics.py`, `test_config_validation.py` (rewrite assertions against §3 schema), `test_recipe_runner.py`, `test_event_historian.py` (CSV parts move to plugin tests in P6; keep SimEvent/ABC tests), `test_mqtt_publisher.py`.

### P0.4 pyproject.toml

```toml
[project]
name = "simengine"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "pyyaml>=6.0", "ruamel.yaml>=0.18", "numpy>=1.24", "scipy>=1.10",
  "opcua>=0.98.13", "paho-mqtt>=2.0", "flask>=3.0",
]

[project.optional-dependencies]
sparkplug = ["mqtt-spb-wrapper>=2.0"]
historian-influx = ["influxdb-client>=1.30"]
historian-neo4j = ["neo4j>=5.0"]
analysis = ["pandas>=2.0"]
dev = ["pytest>=7.0", "pytest-cov>=3.0", "flake8>=6.0", "black>=23.0"]
```

**SparkplugB library decision (binding):** use **`mqtt-spb-wrapper`** (pip-installable, maintained, wraps Eclipse Tahu payloads). If at implementation time it proves unsuitable (API break, packaging failure), the fallback is: vendor `sparkplug_b.proto` from the Eclipse Tahu repository, generate `sparkplug_b_pb2.py` with `protoc`, commit the generated file under `src/simengine/publishers/_sparkplug_pb/`, and use `paho-mqtt` directly. Do not evaluate other libraries.

### Gate P0

```bash
pip install -e ".[dev]"
python -c "import simengine"
pytest tests/ -v          # keep-list tests pass (imports fixed, no engine yet)
```

---

## 2. Phase 1 — The Snapshot Contract

Everything (publishers, REST, historian events) consumes one frozen contract. Define it first so all later phases code against it.

### P1.1 `engine/snapshot.py` — exact dataclasses

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ProcessValueSnapshot:
    name: str; unit: str; value: float
    alarm_state: str          # "OK" | "HIGH" | "LOW"

@dataclass
class ActiveAlarm:
    code: str                 # e.g. "FM_BEARING_WEAR", "PV_TEMP_HIGH", "CS_JAM"
    severity: str             # "INFO" | "WARNING" | "HIGH" | "CRITICAL"
    source: str               # station name
    text: str                 # human-readable
    activated_at: float       # sim_time seconds

@dataclass
class StationSnapshot:
    name: str
    state: str                # one of the 7 states, P4.2
    health: int; h_max: int
    cycle_phase: float        # 0.0-1.0 progress through current cycle, 0.0 when not PROCESSING
    parts_made: int; good: int; scrap: int; rework: int; defective: int
    availability: float; performance: float; quality: float; oee: float
    time_in_state: dict = field(default_factory=dict)  # state -> accumulated seconds
    process_values: list = field(default_factory=list) # list[ProcessValueSnapshot]
    alarms: list = field(default_factory=list)         # list[ActiveAlarm]

@dataclass
class BufferSnapshot:
    name: str; level: int; capacity: int

@dataclass
class LineSnapshot:
    run_id: str; scenario: str; sim_time: float; step_count: int
    line_state: str           # "RUNNING" | "CHANGEOVER" | "STOPPED"
    speed_ratio: float
    throughput: float         # parts per sim-second, cumulative
    total_wip: int; total_good: int; total_scrap: int
    oee: float                # bottleneck model, P4.5
    stations: dict = field(default_factory=dict)   # name -> StationSnapshot
    buffers: dict = field(default_factory=dict)    # name -> BufferSnapshot
    shift: Optional[dict] = None                   # shift_manager passthrough or None
    recipe: Optional[dict] = None                  # recipe state passthrough or None
```

Snapshots are **built fresh each step** by `LineEngine.snapshot()` and are read-only to consumers. JSON serialization = `dataclasses.asdict` (REST returns exactly this shape).

### Gate P1

`tests/test_snapshot.py`: construct nested snapshot, `asdict` round-trip, JSON-serializable via `json.dumps`.

---

## 3. Config Schema (exhaustive for v1)

`config/scenarios.yaml`. Carried keys keep parent semantics; new keys marked ★.

```yaml
demo_line:
  description: "3-station demo"
  enterprise: "Acme"          # ISA-95 names, all optional w/ defaults as in parent
  site: "Plant1"
  area: "Area01"
  line_name: "Line1"
  warm_up_time: 0             # steps
  sim_step: 1.0               # seconds; fixed at 1.0 for v1 (key reserved)
  stations:                   # ★ renamed from 'machines'; same min-2 rule
    - name: Press01
      cycle_time: 12.0        # OR target_ppm (60/ppm precedence, as parent)
      defect_rate: 0.02
      health:                 # ★ replaces parent health_states, run-to-failure only
        h_max: 5
        p_degrade: 0.001      # per-step degrade probability
        mttr: {distribution: lognormal, mean: 120, std: 30}
      failure_modes:          # unchanged parent schema (name/type/mttf/mttr)
        - name: bearing_wear
          type: wearout
          mttf: {distribution: weibull, shape: 2.0, scale: 20000}
          mttr: {distribution: lognormal, mean: 300, std: 60}
      cycle_stops:            # ★ NEW, P4.3
        - reason: CS_JAM
          mtbe: {distribution: exponential, mean: 900}   # mean time between events
          duration: {distribution: lognormal, mean: 25, std: 10}
      process_values:         # ★ NEW, §5
        - name: RamForce
          unit: kN
          profile: cycle_peak
          baseline: 0.0
          peak: {distribution: normal, mean: 850, std: 15}
          health_drift: 0.02
          alarm_high: 920
        - name: OilTemp
          unit: degC
          profile: first_order_lag
          setpoint: 55.0
          tau: 300
          initial: 20.0
          noise: {distribution: normal, mean: 0, std: 0.4}
          health_drift: 0.05
          alarm_high: 68
        - name: StrokePos
          unit: mm
          profile: cycle_ramp
          range: [0.0, 320.0]
          noise: {distribution: normal, mean: 0, std: 0.05}
      spc:                    # optional, parent semantics, measured value = cycle time
        enabled: false
  buffers:                    # exactly len(stations)-1, parent rule
    - {name: B1, capacity: 10}
    - {name: B2, capacity: 10}
  shifts: {}                  # optional, parent schema
  comms:                      # ★ per clone_target_architecture §3
    opcua: {enabled: true, port: 4840}
    opcua_mqtt: {enabled: true, broker: "mqtt://mosquitto:1883",
                 publisher_id: "simengine-line1", flat_topics: true, publish_interval: 1}
    sparkplugb: {enabled: false, broker: "mqtt://mosquitto:1883",
                 group_id: "Area01", edge_node_id: "Line1"}
  historians: []              # ★ plugin names, e.g. ["csv"]; empty default
```

Validation additions to `config/loader.py` (same composable style as parent): `validate_process_values` (profile in {cycle_peak, first_order_lag, cycle_ramp, constant_noise}; required keys per profile per §5; alarm_high > alarm_low when both), `validate_cycle_stops` (mtbe/duration are valid distributions), `validate_comms` (broker URI shape, port int), `validate_health` (h_max positive int, p_degrade in [0,1], mttr required).

Ship three starter scenarios: `demo_line` (above), `two_station_minimal`, `press_line_8` (8 stations, all features on).

---

## 4. Phase 2 — Engine Core (`engine/`)

### P4.1 Health model (`engine/health.py`)

Per station, per step (in this order):

```
if state == UNDER_REPAIR:
    repair_remaining -= sim_step
    if repair_remaining <= 0: health = 0; repair_remaining = 0; active_failure_mode = None
elif health >= h_max:                      # just failed this step or earlier
    if repair_remaining <= 0:              # sample once
        mttr_dist = active_failure_mode.mttr if active_failure_mode else station.health.mttr
        repair_remaining = max(sim_step, mttr_dist.sample())
else:
    if rng.random() < p_degrade: health += 1
```

Failure-mode attribution: at engine start, each configured failure mode samples a time-to-fire from its MTTF distribution; the mode with the earliest pending fire time becomes `active_failure_mode` when health first reaches `h_max` (competing-risks, reusing `FailureModeManager` exactly as the parent does). Its `name` feeds the `FM_*` alarm code (P4.6). MTTF scaling rule carried from parent: divide sampled MTTF by `h_max` when `h_max > 1`.

### P4.2 Station state machine (`engine/station.py`)

Seven states, and the **detection precedence is normative** (carried from parent, validated behavior):

```
1. health >= h_max and repair_remaining > 0  -> UNDER_REPAIR
2. health >= h_max                            -> FAILED
3. active cycle_stop                          -> IDLE with CS_* alarm active (see P4.3)
4. downstream buffer full (no space)          -> BLOCKED
5. upstream buffer empty (no part) and no part in station -> STARVED
6. 0 < health < h_max                         -> DEGRADED (still processes!)
7. part in station, cycle in progress         -> PROCESSING
8. else                                       -> IDLE
```

DEGRADED is a *reporting* state: a degraded station continues processing (cycle proceeds); state reports DEGRADED unless rule 1–5 applies. (This matches the parent's semantics where DEGRADED outranks PROCESSING for display.)

Cycle mechanics per step:

```
if station can work (not UNDER_REPAIR/FAILED, not cycle-stopped, has part):
    cycle_elapsed += sim_step
    if cycle_elapsed >= cycle_time:
        complete_cycle()          # quality roll P4.7, push to downstream buffer if space
        cycle_elapsed = 0
        pull next part from upstream buffer if available
if no part and upstream buffer non-empty and not blocked-from-pulling:
    pull part; cycle_elapsed = 0
```

First station pulls from an infinite source; last station pushes to an infinite sink (counted, not stored). `cycle_phase = cycle_elapsed / cycle_time`.

### P4.3 Cycle stops

Per configured stop: at run start sample `next_fire = mtbe.sample()`. Each step while station is PROCESSING, decrement by `sim_step`; at <= 0, activate: sample `stop_remaining = duration.sample()`, raise `CS_*` alarm, halt cycle progress. While active, decrement `stop_remaining`; at <= 0, clear alarm, resample `next_fire`. Cycle-stop downtime accumulates to `time_in_state["MINOR_STOP"]` (feeds OEE Performance, not Availability — P4.5).

### P4.4 Determinism

`LineEngine.step()` seeds once per step: `rng = random.Random((seed + step_count) % 2**31)` and passes this `rng` (plus a same-seeded `numpy.random.Generator`) into every model. No global seeding. Same `--seed` → identical trajectory, snapshot-for-snapshot.

### P4.5 KPIs (`engine/line.py` + carried kpi math)

Per station, shift-relative deltas exactly as parent:
- Availability = 1 − (down_time / total_time), where down_time = FAILED + UNDER_REPAIR time only.
- Performance = (parts_made × cycle_time) / (total_time − down_time), capped at 1.0. Minor-stop time thus lands here.
- Quality = good / max(1, parts_made).
- Line OEE = bottleneck model carried from parent `calculate_line_level_oee`.

### P4.6 Alarm registry (`engine/alarms.py`)

```python
ALARM_CATALOG = {
  # code: (severity, text_template)
  "FM_*":            ("CRITICAL", "{station}: failure - {mode_name}"),   # code = "FM_" + mode_name.upper()
  "PV_{name}_HIGH":  ("HIGH",     "{station}: {pv} {value:.1f}{unit} above {limit}"),
  "PV_{name}_LOW":   ("HIGH",     "{station}: {pv} {value:.1f}{unit} below {limit}"),
  "CS_{reason}":     ("WARNING",  "{station}: cycle stop - {reason}"),
  "MT_REPAIR":       ("INFO",     "{station}: under repair, {remaining:.0f}s remaining"),
}
```

`AlarmRegistry.raise_(code, station, **ctx)` / `clear(code, station)`; active set is edge-detected (raise/clear events emitted once). `StationSnapshot.alarms` lists active alarms; the OPC UA `ActiveReasonCode` node carries the highest-severity active code (ties: most recent).

### P4.7 Quality roll (salvaged Tier-3 logic)

On cycle completion: `p_defect = min(1.0, defect_rate * (health_multiplier ** health))` (health_multiplier default 1.0 → flat rate). Defective parts: if rework configured, roll `rework_success_rate` → good (rework counted); else scrap. Counters: `parts_made`, `good`, `scrap`, `rework`, `defective` — these feed `line_state.py`'s adapter (replace the 6 `machine_obj` attribute reads in `sync_machine` with these counters).

### Gate P2

`tests/test_station_engine.py` (new, comprehensive):
- 2-station line, seed 42, 1000 steps: deterministic snapshot hash equals itself on re-run.
- Starvation/blocking: cycle_time asymmetry produces STARVED downstream / BLOCKED upstream states.
- Run-to-failure: station with p_degrade=1, h_max=3 fails on step 3, is UNDER_REPAIR for ceil(mttr) steps, recovers to health 0. (CBM, an early no-downtime repair path, was evaluated and removed post-launch — see docs/superpowers/specs/2026-07-22-remove-cbm-design.md.)
- Quality conservation: `good + scrap + defective_not_reworked == parts_made` after any run.
- Cycle stop fires, halts progress, clears, refires.
- OEE: hand-computed fixture for a 100-step scripted scenario matches to 1e-9.

```bash
pytest tests/test_station_engine.py tests/test_snapshot.py -v
```

---

## 5. Phase 3 — Process Values (`engine/process_values.py`)

Exact formulas. `phase` = station `cycle_phase`; `h` = health; `drift = 1 + health_drift * h`; all `dist.sample()` through DistributionFactory with the step RNG.

| Profile | Formula per step | Required keys |
|---|---|---|
| `cycle_peak` | Not PROCESSING → `value = baseline`. PROCESSING: at cycle start sample `peak_i = peak.sample() * drift`; `value = baseline + peak_i * sin(pi * phase)` | baseline, peak; optional health_drift (default 0), alarm_high/low |
| `first_order_lag` | `target = setpoint * drift` when station working (PROCESSING/DEGRADED), else `target = ambient` (default = initial). `value += (target - value) * (sim_step / tau)`; then `value += noise.sample()` | setpoint, tau, initial; optional noise, health_drift, alarm_high/low |
| `cycle_ramp` | Not PROCESSING → `value = range[0]`. PROCESSING: `value = range[0] + (range[1]-range[0]) * phase + noise.sample()` | range; optional noise, alarm_high/low |
| `constant_noise` | `value = mean * drift + noise.sample()` always | mean; optional noise, health_drift, alarm_high/low |

Threshold checking each step: `value > alarm_high` → raise `PV_{NAME}_HIGH`; `value < alarm_low` → `PV_{NAME}_LOW`; else clear both. Hysteresis: clear only when value re-crosses the limit by 1% of the limit (prevents alarm chatter).

Optional SPC hookup: if station `spc.enabled`, feed each configured process value's cycle-end reading into the carried `ProcessMonitor` (`runtime/spc.py`) — one monitor per (station, pv).

### Gate P3

`tests/test_process_values.py`: first_order_lag converges to setpoint*drift within 5*tau; cycle_peak returns to baseline between cycles; ramp endpoints exact ± noise σ; alarm raise/clear with hysteresis; degraded health measurably shifts values; determinism under fixed seed.

---

## 6. Phase 4 — OPC UA Publisher, REST, UI

### P6.1 Publisher ABC (`publishers/__init__.py`)

```python
class StatePublisher(ABC):
    def on_run_start(self, snapshot: LineSnapshot) -> None: ...
    def publish(self, snapshot: LineSnapshot) -> None: ...
    def on_run_end(self) -> None: ...
    def close(self) -> None: ...
```

`CompositePublisher(list)` fans out; publisher construction from `comms` config via a `build_publishers(config) -> CompositePublisher` factory with guarded imports (opcua_mqtt/sparkplugb only imported if enabled).

### P6.2 OPC UA server publisher

Lift from parent `opcua_server.py` into `publishers/opcua_nodes.py`: `_nid`, `_qn`, `CachedOpcuaNode` (with dead-bands), `create_machine_node` (rename station), `create_storage_unit_node`, `create_alarms_node`, plus new `create_process_values_node` (one Float variable per PV under `ProcessValues/`) and `ActiveReasonCode`/`ActiveReasonText` string variables under `Alarms/`. Address space = same ISA-95 shape as parent (Enterprise/Site/Area/{line}_Equipment/...), so parent-era OPC UA clients browse identically. Writes: collect dirty values per publish, flush via one `server.set_attributes` batch (parent perf spec P2 built in from day one). Drop from parent: SPC chart nodes (plugin era), failure-mode stats nodes (replaced by reason codes), shift nodes kept only if `shifts` configured.

### P6.3 Run manager (`runtime/run_manager.py`)

Owns the engine thread. States: IDLE → RUNNING → STOPPING → IDLE. `start(scenario_name, seed=None, speed_ratio=1.0)` → validates config, builds engine + publishers, generates `run_id = f"{scenario}_{YYYYMMDD_HHMMSS}"`, spawns loop thread (1 Hz wall-locked: `sleep(max(0, sim_step/speed_ratio - elapsed))`). `stop()` sets a flag; thread calls `on_run_end` on publishers and exits cleanly. Exactly one run at a time; `start` while RUNNING → 409. Recipe mode: `start_recipe(name, seed)` drives carried `recipe_runner` (its two imports now point at `LineEngine`/`run_manager.run_segment`).

### P6.4 REST (`api/rest.py`)

Endpoints exactly as `clone_target_architecture.md` §4. Implementation notes: single Flask app created in `simengine.__main__`; `GET /api/v1/state` returns `asdict(run_manager.latest_snapshot)` or 404 if no run; mutating scenario/recipe endpoints call carried validators and write YAML via ruamel (preserving comments, as parent webui does); `PUT /api/v1/comms` validates and persists, response includes `{"applies": "next_run"}`. Errors: 400 validation (body = validator message), 404 unknown name, 409 run-state conflict.

### P6.5 UI (`api/ui/`)

Three templates (Jinja, no build step, vanilla JS polling `GET /api/v1/state` at 2 s):
- `dashboard.html` — line KPI header; station cards: state (color-coded 7 states), health bar, active alarm code+text, PV readouts.
- `configure.html` — scenario list + editor (adapt parent `config.html` CRUD skeleton), recipe list + editor.
- `comms.html` — three protocol checkboxes with per-protocol fields (§3 comms block), topic-root preview text, plugin installed/not-installed list (from a `GET /api/v1/plugins` helper endpoint returning importability of each known extra).
Header on all pages: scenario picker, seed field, speed ratio, Start/Stop, run_id + status.

### Gate P4

```bash
python -m simengine --scenario demo_line --seed 42 &   # starts REST :8080 + OPC UA :4840
curl -s localhost:8080/api/v1/state | python -m json.tool          # full snapshot JSON
curl -s -X POST localhost:8080/api/v1/runs -d '{"scenario":"demo_line","seed":7}' -H 'Content-Type: application/json'
# OPC UA: python-opcua client browses Enterprise/.../Press01_Equipment/ProcessValues/OilTemp, reads a float
pytest tests/test_rest_api.py tests/test_opcua_publisher.py -v
```

`test_rest_api.py`: full CRUD + run lifecycle + 409 double-start via Flask test client. `test_opcua_publisher.py`: build address space against config, assert node paths and PV/reason-code nodes exist, batched write count per publish ≤ dirty count + 1.

---

## 7. Phase 5 — MQTT Publishers

### P7.1 `publishers/opcua_mqtt.py`

Carry parent `src/mqtt_publisher.py`; adapt input from `opcua_vars` dict to `LineSnapshot`. Payload field naming: `{Station}.{Metric}` and `{Station}.PV.{Name}`. Keep: Part 14 JSON envelope, MQTT 5 `ContentType application/json+opcua`, message expiry, status-topic Will, optional flat topics `simengine/{line}/{station}/{metric}`.

### P7.2 `publishers/sparkplugb.py` (new)

- Library per §1 P0.4 (binding decision: `mqtt-spb-wrapper`, fallback vendored pb2).
- Topics: `spBv1.0/{group_id}/NBIRTH|NDATA|NDEATH/{edge_node_id}` and `.../DBIRTH|DDATA|DDEATH/{edge_node_id}/{station}`.
- DBIRTH per station on `on_run_start`: every metric with name, alias (stable int, assigned in snapshot iteration order), datatype (Int32/Float/String/Boolean), initial value. Metrics: `State` (String), `Health` (Int32), `PartsMade/Good/Scrap` (Int32), `OEE/Availability/Performance/Quality` (Float), `ActiveReasonCode` (String), one Float per PV (`PV/{name}`).
- NDATA/DDATA per publish: **delta only** — compare against last-sent per-metric value, send changed metrics with aliases. Full rebirth on NCMD `Node Control/Rebirth` = true (subscribe `spBv1.0/{group}/NCMD/{edge_node}`).
- NDEATH via MQTT Will with bdSeq; seq number cycling 0-255 per spec.
- Separate MQTT client + client_id (`simengine-spb-{edge_node_id}`) from the Part 14 publisher, per architecture doc §3.2.

### Gate P5

`docker compose up mosquitto`; run engine with both MQTT publishers enabled;
`mosquitto_sub -t 'opcua/#' -v` shows JSON envelopes; `mosquitto_sub -t 'spBv1.0/#' -v` shows binary frames; `tests/test_sparkplugb.py` (mocked client): DBIRTH metric set matches snapshot fields, DDATA contains only changed aliases, rebirth on NCMD, seq wraps at 255.

---

## 8. Phase 6 — Plugins & Compose Profiles

- `events/` already holds `SimEvent` + `EventHistorian` ABC. Registry per architecture doc §2 (`plugins.py`, guarded importlib).
- `historian-csv`: move parent `CSVHistorian` to `src/simengine_historian_csv/`; edge-detected event collection adapted to consume `LineSnapshot` diffs (state transitions, alarm raise/clear, run start/end).
- `historian-influx`: parent `InfluxDBHistorian` + telegraf generator + grafana assets under compose `--profile influx`.
- `historian-neo4j`: parent module, `--profile graph`.
- Compose: default services `simengine` + `mosquitto` only; profiles `influx`, `graph`.
- Dockerfile: multi-stage per parent performance spec D2.

### Gate P6

Core install without extras: engine runs, `historians: ["csv"]` fails with the clear install-hint error. `pip install -e ".[historian-influx]"` + `--profile influx` up: events land in InfluxDB (validation query by run_id).

---

## 8b. Phase 7 — Knowledge Graph, MCP Server, BYO-Key Chat

Full rationale and design in `docs/specs/clone_ai_interface_spec.md` — that document governs this phase's semantics; this section is the task breakdown. Decisions already made: MCP tools have full control (no gating flag), chat is Anthropic-only, MCP serves both external hosts and the UI chat.

### P7.1 Knowledge graph (`engine/knowledge_graph.py`, stdlib-only)

- Node types: `Enterprise, Site, Area, Line, Station, Buffer, ProcessValue, FailureMode, AlarmCode, CycleStopReason, Scenario, Recipe, Metric`; edges: `CONTAINS, FEEDS, HAS_PV, HAS_FAILURE_MODE, CAN_RAISE, MEASURED_BY, RUNS`.
- Every ProcessValue/Metric node carries all wire addresses: OPC UA NodeId, SparkplugB `{group, edge_node, device, metric}`, flat MQTT topic, REST JSON path (exact shape in the AI interface spec §1).
- Built once at run start from config; deterministic. `LineEngine` (or run_manager) owns the instance.
- `GET /api/v1/kg` with `?type=`, `?station=`, `?edge=` filters, JSON node-link output.
- `tests/test_knowledge_graph.py`: node/edge counts for `demo_line`; every configured PV present with all four addresses; two builds from the same config → byte-identical JSON.

### P7.2 MCP server (`api/mcp_server.py` + tool registry)

- Dep: `mcp>=1.0` (core). FastMCP, Streamable HTTP transport, port **8765**, path `/mcp`, started in `simengine.__main__` alongside REST.
- Tool registry module shared by MCP and chat; every tool wraps the same function REST uses.
- Read tools: `get_line_state, get_station, get_run_status, query_knowledge_graph, resolve_metric, list_scenarios, get_scenario, list_recipes, get_recipe, explain_alarm`.
- Control tools (always on): `start_run, start_recipe, stop_run, update_scenario, update_recipe, set_comms` — config writes go through the existing validators; invalid input → tool error, file untouched.
- `tests/test_mcp_tools.py`: each tool against a mocked run_manager; `update_scenario` with invalid YAML leaves file unchanged; `start_run` during an active run returns a tool error.

### P7.3 BYO-key chat (`api/chat.py` + `ui/chat.html`)

- Optional extra: `chat = ["anthropic[mcp]>=0.50"]`; lazy import, page degrades with install hint.
- Agent loop: `client.beta.messages.tool_runner(...)`, model default `claude-opus-4-8`, `thinking={"type": "adaptive"}`, tools = the P7.2 registry as direct function references.
- System prompt assembled from the KG (topology summary, stations, PVs/units, alarm catalog) as the stable cached prefix.
- `POST /api/v1/chat` → SSE stream of `{type: text|tool_use|tool_result|done}` events; `DELETE /api/v1/chat` clears history; key held in process memory per session only — never disk/config/logs; status endpoint reports only `chat_key_set: bool`.
- UI: 4th page "Assistant" — key field, model picker, chat pane, rendered tool-call traces.
- `tests/test_chat.py`: mocked Anthropic client; SSE event shape; key-never-persisted check (run a turn, grep `config/`, `results/`, captured logs for the key string).

### P7.4 Docs

- External MCP host connection guide (Claude Desktop/Code config snippet with `"url": "http://<host>:8765/mcp"`).
- Security note: control tools always on → treat :8765 like :8080 (trusted network only; reverse proxy for anything else). Chat key requires TLS beyond localhost.

### Gate P7

```bash
python -m simengine --scenario demo_line --seed 42 &
# External MCP host (Claude Code / mcp CLI) connects to http://localhost:8765/mcp,
# lists 16 tools, get_line_state returns the live snapshot, start_run/stop_run round-trips.
pytest tests/test_knowledge_graph.py tests/test_mcp_tools.py tests/test_chat.py -v
# Manual: UI chat with a real key answers "what's the oil temperature on Press01?"
# via resolve_metric, with the tool trace visible.
```

---

## 9. Acceptance (whole project)

1. `pip install -e ".[dev]" && pytest tests/ -v` — all green.
2. `python -m simengine --scenario press_line_8 --seed 42` for 300 steps twice → identical final snapshot JSON (determinism).
3. UaExpert/opcua-client browses the ISA-95 tree; PV floats update ~1 Hz; a forced failure shows `ActiveReasonCode = FM_BEARING_WEAR`.
4. With all three comms enabled: OPC UA TCP, `opcua/#` JSON, and `spBv1.0/#` Protobuf all live simultaneously on one Mosquitto, disjoint topics.
5. Full run lifecycle through REST only (no CLI): create scenario → start → observe state → stop.
6. Memory flat over a 2-hour run (no unbounded lists — PV histories are not retained in core; SPC uses the parent's bounded deques + Welford if the parent perf spec P1 was applied).
