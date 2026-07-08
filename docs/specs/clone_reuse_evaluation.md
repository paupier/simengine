# Clone Reuse Evaluation — Real-Time Station Simulation Engine

**Status:** Evaluation
**Refined by:** `clone_target_architecture.md`, which narrows the clone's core to engine + OPC UA / OPC UA-over-MQTT / SparkplugB / REST and moves historians, Telegraf/Grafana, Neo4j, and analysis tooling to optional plugins. Where the two documents differ on what is "core", the architecture doc governs (see its §7 tier-change table).
**Purpose:** Assess what can be preserved or inherited when cloning this project into a new system: a real-time simulation engine for production equipment that is less strictly DES-based, with detailed per-station machine makeup — continuous float outputs (temperatures, forces, distance measurements) configured per station, and actual alarm reasons for health degradation and cycle stops. The clone is purely a simulation engine consumed by external applications (e.g. FactoryTalk Optix) as a data source in place of PLC logic. Simantha becomes optional or removed.

---

## Headline Finding

**Simantha is already quarantined.** A full-repo audit found only **4 files that hard-import Simantha**:

| File | Import |
|---|---|
| `src/opcua_server.py:16-17` | `from simantha import Source, Machine, Buffer, Sink, System, Maintainer`; `from simantha.simulation import Environment` |
| `src/advanced_machine.py:13` | `from simantha import Machine` (subclass) |
| `src/quality_machine.py:19` | `from simantha import Machine, Sink` (mixin/subclass) |
| `src/priority_maintainer.py:8` | `from simantha import Maintainer` (subclass) |

One file is a deliberate duck-typed shim (`src/line_state.py`), one has light residual coupling (`src/event_historian.py` fallback reads). **Everything else — analytics, config, historians, publishers, web UI, Telegraf generation, reporting tools, the entire Docker stack — is framework-agnostic and carries over unchanged.** Roughly 85% of the codebase survives the clone as-is.

**Second-order win:** a large fraction of `opcua_server.py`'s complexity exists solely to fight Simantha's per-step re-initialization model — the health-restorer monkey-patch, buffer-state persistence closures, the sink.level monotonic counter, the `Sink.level_data` memory-leak patch, the `_counting_active` warm-up guard. Every "Critical Rule" in CLAUDE.md that documents a Simantha workaround **simply disappears** in a native fixed-timestep engine. The clone is simpler than the parent, not just different.

---

## Tier 1 — Reuse As-Is (zero changes)

Verified: no `import simantha`, no Simantha object-attribute reads.

| Module | LOC | Role in the clone |
|---|---|---|
| `src/failure_modes.py` | 376 | **The stochastic backbone.** `DistributionFactory` (constant/exponential/weibull/lognormal/normal/uniform) + `FailureModeManager` (competing-risks MTTF/MTTR) are pure scipy + config dicts. In the clone they additionally drive process-value noise, drift rates, and cycle-stop timing — one distribution vocabulary for everything. |
| `src/spc_analytics.py` | 411 | `ProcessMonitor.add_measurement(value: float)` takes **raw floats** (spc_analytics.py:332). Feed it the new temperature/force/distance streams directly — X-bar/R charts, Cp/Cpk, Western Electric rules work unchanged on any float signal. Note: the *measurement synthesis* is not in this module (see Tier 5). |
| `src/shift_manager.py` | 389 | Pure name-keyed dict accumulator (`record_state(machine_name, state, delta)`). No engine coupling at all. |
| `src/config_loader.py` | 642 | Pure YAML validation with a composable validator pattern — extend with the new station schema (process_values, alarm reasons) without touching existing validators. |
| `src/event_historian.py` | 726 | `EventHistorian` ABC, `CSVHistorian`, `InfluxDBHistorian`, `CompositeHistorian`, `SimEvent` are dict consumers. Two residual duck-typed fallbacks to remove: `buffer_obj.level` reads (event_historian.py:623, 656) and `getattr(machine, '_scrap_count'/...)` fallbacks (572, 596, 600) — the preferred dict-based path (`machine_totals`) already exists; make it the only path. |
| `src/neo4j_historian.py` | 489 | Pure Cypher-from-dicts. "Machine"/"Buffer" are graph labels, not objects. |
| `src/mqtt_publisher.py` | 223 | Pure. OPC UA-over-MQTT / flat-topic publishing carries straight over — same bolt-on surface for the clone. |
| `src/fault_injector.py` | 251 | Already mutates `machine_health` / `machine_metrics` **dicts** owned by the main loop — exactly the contract the new engine will offer. |
| `src/experiment_writer.py` | 85 | Pure. |
| `docker/webui/app.py` + templates | 1945 | Pure OPC UA client + Flask + subprocess management. Works against the clone's server unchanged as long as the ISA-95 browse paths are kept (they should be — see Tier 2). |
| `docker/telegraf/generate_telegraf_conf.py` | 434 | Config-in, telegraf.conf-out. No engine dependency. |
| `docker/` compose stack (InfluxDB, Grafana, Telegraf, Mosquitto, optional Neo4j/monitoring) | — | Entire deployment pipeline carries over. |
| `tools/report_engine.py`, `tools/analyze_historian.py` | 1643 + 766 | Operate on historian CSVs/metrics. Unchanged. |
| ~15 Simantha-free test files | — | `test_spc_analytics`, `test_failure_modes`, `test_distribution_validation`, `test_config_validation`, `test_event_historian`, `test_fault_injector`, `test_mqtt_publisher`, `test_recipe_runner`, `test_neo4j_historian`, `test_report_engine`, `test_telegraf_generator`, `test_webui`, `test_topology`, and more. |

---

## Tier 2 — Reuse With Light Adaptation

| Module | Adaptation required |
|---|---|
| `src/line_state.py` (93 LOC) | **The designed isolation boundary.** `sync_machine(name, machine_obj)` reads exactly 6 counter attributes (`parts_made`, `_good_count`, `_scrap_count`, `_defective_count`, `_rework_count`, `_rework_success_count` — line_state.py:87-93); `sync_sink()` already takes an int. Replace those 6 reads with counters from the new station model (~6-line adapter). Everything downstream reads `LineState`, never the engine. |
| `src/recipe_runner.py` (724 LOC) | Orchestration-only: no Simantha import; holds `system/source/sink/machines` as **opaque handles** and delegates to `build_simantha_system` / `run_segment` (recipe_runner.py:406-412). Swap those two imports for the new engine's equivalents; recipe parsing, segment overrides, changeover sampling, and all recipe OPC UA state are unchanged. |
| OPC UA node builders + analytics helpers inside `opcua_server.py` | **Already Simantha-free** — they take config primitives, not objects: `create_machine_node(parent, idx, name, enable_health, enable_failure_modes, failure_mode_names, enable_spc, enable_quality_routing, node_prefix)` (opcua_server.py:276), `create_machine_asset_node` (401), `create_storage_unit_node` (434), `create_alarms_node` (466), `create_spc_node` (518), `create_shift_management_node` (582), `update_alarm_variables` (837), `accumulate_time` (878), `calculate_oee` (902), `detect_machine_alarms` (712), `detect_buffer_alarms` (786), `_nid`/`_qn` helpers, and `CachedOpcuaNode` (69-172). **Extract these into `opcua_nodes.py` / `kpi.py` modules and lift them wholesale.** The ISA-95 address-space shape is exactly what FactoryTalk Optix consumes — preserving it means Optix projects built against the parent work against the clone. |
| Main-loop *shape* of `run_segment()` | Keep the skeleton: 1 Hz wall-clock-locked step loop, stop conditions (`max_sim_time` / `target_quantity`), `SimSpeedRatio`, run_id propagation, warm-up gating, per-step seeding (`(seed + step_count) % 2^31`). Delete the Simantha-workaround interior (see Tier 4). |

---

## Tier 3 — Extract the Logic, Discard the Class

The three Simantha subclasses (~600 LOC total). Their pure decision logic extracts in a few dozen lines; the subclass plumbing is Simantha-specific and is discarded.

| Module | Salvage | Discard |
|---|---|---|
| `src/advanced_machine.py` (283) | Nothing beyond what it already delegates to the pure `FailureModeManager`. The MTTF scaling rule (sampled MTTF ÷ `failed_health` for multi-state machines) moves into the new health model. | The `Machine` subclass, `env.now` hooks, `get_time_to_degrade`/`restore` overrides. |
| `src/quality_machine.py` (206) | `_quality_route()` decision math: defect probability = `defect_rate × health_multiplier^health`, rework success sampling, scrap/rework/good counter increments. | `output_addon_process()`, `_redirect_to()`, `reserved_vacancy` bookkeeping — all Simantha part-object routing. In the clone, quality is a **per-cycle outcome** (each completed cycle rolls good/scrap/rework), not a part-object diversion through a routing graph. |
| `src/priority_maintainer.py` (123) | FIFO/SPT/priority/bottleneck strategy functions — pure list-selection logic. | The `Maintainer` subclass and Simantha queue-attribute names (`time_entered_queue`, `cm_distribution`). |

---

## Tier 4 — Replace: the New Engine Core

Replace Simantha's DES with a **fixed-timestep station state-machine engine** (`station_engine.py`). This is greenfield but small — a few hundred lines — because the hard parts already exist as spec in this repo:

- **Station state machine:** IDLE → PROCESSING → (cycle complete) with BLOCKED/STARVED derived from downstream/upstream buffer levels, and DEGRADED/FAILED/UNDER_REPAIR from the health model. The 7-state taxonomy and its detection order (CLAUDE.md "State detection order") carry over verbatim as the specification.
- **Buffers:** plain bounded integer counters. Without Simantha part objects there is no reservation protocol (`reserved_vacancy`) to maintain.
- **Health/degradation:** the existing `health_states` model (`h_max`, `p_degrade`, `cbm_threshold`, CBM vs run-to-failure semantics) re-implemented natively (~50 LOC). Today it is already driven from the main loop via monkey-patches — the clone makes it a first-class engine feature instead of a workaround.
- **Repair:** the `machine_repair_remaining` countdown pattern carries over directly, minus the monkey-patch delivery mechanism.
- **Determinism:** keep per-step seeding `(seed + step_count) % 2^31`. With no engine re-initialization to fight, reproducibility becomes trivial rather than hard-won.

What disappears entirely (all CLAUDE.md "Critical Rules" that exist to fight Simantha):
`_install_health_restorer` monkey-patch, `_persist_buffer_state` closures, sink.level monotonic-counter resync, the `Sink.level_data` memory-leak patch, the `ViewService`/`internal_server` patches, `_counting_active` vs `env.now` warm-up duality, the "never modify cycle_time after start" rule, and the carryover dict for cycle_time > sim_step.

---

## Tier 5 — Genuinely New (does not exist in the parent)

### 1. Process-value models (temperatures, forces, distances)

Today the **only** continuous float signal synthesized is the SPC measurement: `measurement = cycle_time × (1 + gauss(0, noise_cv))`, optionally health-scaled (opcua_server.py:1429-1441). There is no temperature, force, pressure, vibration, torque, or distance simulation anywhere in `src/`. That 12-line pattern is the seed — generalize it into a configurable `ProcessVariable` model per station:

```yaml
stations:
  - name: Press01
    cycle_time: 12.0
    process_values:
      - name: RamForce
        unit: kN
        profile: cycle_peak          # rises to peak mid-cycle, returns to baseline
        baseline: 0.0
        peak: {distribution: normal, mean: 850, std: 15}
        health_drift: 0.02           # peak drifts +2% per health state
        alarm_high: 920              # → PV_FORCE_HIGH reason code
      - name: OilTemp
        unit: degC
        profile: first_order_lag     # thermal: approaches setpoint with time constant
        setpoint: 55.0
        tau: 300
        noise: {distribution: normal, mean: 0, std: 0.4}
        health_drift: 0.05
        alarm_high: 68
      - name: StrokePosition
        unit: mm
        profile: cycle_ramp          # deterministic within-cycle trajectory + noise
        range: [0, 320]
        noise: {distribution: normal, mean: 0, std: 0.05}
```

Profile shapes (`cycle_peak`, `first_order_lag`, `cycle_ramp`, `constant_noise`) are evaluated per step from cycle phase + health state; all randomness flows through the existing `DistributionFactory`. Each process value gets a float OPC UA node under the station's `ProcessValues/` folder, published through the same `CachedOpcuaNode` dead-band machinery and picked up by the same Telegraf generator — this is what makes the clone a PLC-replacement data source for Optix.

### 2. Reason-coded alarm model

Today's alarm layer is **boolean-flag, not reason-coded**: exactly 3 machine alarm categories (`MachineFailure`, `Maintenance`, `QualityAlert`) plus 2 buffer levels, surfaced as booleans + a generic `LastAlarmMessage` (detect_machine_alarms, opcua_server.py:712-783; create_alarms_node, 466-497). The failure *cause* is modeled in the sim layer (`pending_failure_mode`, config-named modes like "mechanical"/"electrical", `get_active_failure_mode()`) but is **never wired into the alarm surface** — the failure alarm text is the generic "health degraded to critical state".

The clone needs an alarm registry:

- **Reason codes** with taxonomy: `FM_*` (failure modes: `FM_BEARING_WEAR`, `FM_DRIVE_FAULT`), `PV_*` (process-value threshold: `PV_TEMP_HIGH`, `PV_FORCE_HIGH`), `CS_*` (cycle stops: `CS_JAM`, `CS_NO_PICK`, `CS_GUARD_OPEN`), `MT_*` (maintenance).
- Each active alarm carries: code, severity, source (station + process value / failure mode), text, activation timestamp.
- OPC UA surface per station: `Alarms/ActiveReasonCode` (string/enum), `ActiveReasonText`, `ActiveAlarmCount`, plus the existing booleans for backward compatibility.
- The existing edge-detection scaffolding (`update_alarm_variables`, historian ALARM events, alarm tuples) is kept — only the flatten-to-boolean layer is replaced by the registry.

### 3. Cycle-stop modeling

Short stops (jam, no-pick, guard-open) distinct from health-degradation failures: frequency and duration each sampled from `DistributionFactory` distributions per configured stop reason, surfaced with `CS_*` reason codes and counted separately from failure downtime (minor-stop time feeds OEE Performance rather than Availability, matching standard OEE practice). New logic, but expressed entirely with the existing distribution/config vocabulary.

---

## Recommended Clone Strategy

1. **Clone the repo preserving history** (the analytics/config/historian modules have meaningful evolution worth keeping).
2. **Extract Tier-2 node builders and helpers** out of `opcua_server.py` into `opcua_nodes.py` / `kpi.py` — do this first, in the clone, since it also derisks any later backports to the parent.
3. **Write `station_engine.py`** (Tier 4): stations, buffers, health, repair, cycle phase.
4. **Rewire `run_segment()`** to the new engine, deleting all Simantha workarounds; adapt `line_state.sync_machine` (6 lines) and `recipe_runner`'s two imports.
5. **Drop the three subclass files** after salvaging the Tier-3 decision logic.
6. **Add Tier-5 models**: process values first (they define the clone's identity as a data source), then the reason-coded alarm registry, then cycle stops.
7. **Remove `simantha` from requirements.** Recommendation: do **not** keep a dual-engine "DES mode" — supporting both complicates the main loop for little gain, and the parent repo remains available for DES-grade material-flow studies. If throughput fidelity is ever needed in the clone, revisit then.

**FactoryTalk Optix impact: none.** The clone exposes the same OPC UA TCP server with the same ISA-95 address-space shape, plus new float nodes under each station's `ProcessValues/` and richer `Alarms/` — Optix consumes it exactly as it would PLC tags, which is the point.

---

## Reuse Summary

| Tier | Content | Approx. LOC | Fate |
|---|---|---|---|
| 1 | Analytics, config, historians, publishers, web UI, Telegraf, tools, Docker, most tests | ~10,000+ | Carry over unchanged |
| 2 | line_state shim, recipe_runner, node builders/KPI helpers, loop skeleton | ~2,000 | Light adaptation / extraction |
| 3 | Three Simantha subclasses | ~600 | Salvage ~100 LOC of logic, discard rest |
| 4 | Simantha + its workarounds in the main loop | ~1,000 | Replace with `station_engine.py` (a few hundred LOC, net simpler) |
| 5 | Process values, reason-coded alarms, cycle stops | 0 today | Greenfield, built on Tier-1 primitives |
