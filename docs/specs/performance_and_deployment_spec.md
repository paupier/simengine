# Performance & Deployment Efficiency Specification

**Status:** Proposed
**Scope:** Runtime processing speed, container/CI deployment footprint, and scenario/model rollout lifecycle.
**Constraint:** All runtime optimizations in this spec are **transparent** — they must not change any observable output (OPC UA values, historian events, KPIs, reproducibility under `--seed`). Behavior-changing optimizations are listed under *Deferred* only.

---

## Part 1 — Runtime Performance

### Baseline (what already works, do not regress)

These existing mitigations are correct and must be preserved by every change below:

| Mitigation | Location |
|---|---|
| `CachedOpcuaNode` write-on-change with dead-bands | `src/opcua_server.py:69-172` |
| `opcua_update_interval` write-gate (skip writes on off-interval steps) | `src/opcua_server.py:~2656` |
| Bounded control-chart deques | `src/spc_analytics.py:92-94` |
| Edge-triggered historian events (state transitions only) | `src/event_historian.py` |
| Web UI OPC UA client singleton (no reconnect per request) | `docker/webui/app.py:518` |
| Per-step seeding for reproducibility | `src/opcua_server.py:2497-2498` — **intentional, keep** |

### P1 — SPC statistics: unbounded memory + O(n) recompute, called twice per step

**Severity: highest.** This is both a memory leak and, on long runs, the dominant CPU cost.

**Finding:**
- `ProcessMonitor.all_samples` is a plain list that appends every measurement forever (`src/spc_analytics.py:329, 339`). It is never capped; only `reset()` clears it, and the main loop never calls `reset()`. RSS grows linearly for the life of the run.
- `get_metrics()` (`src/spc_analytics.py:343-405`) rebuilds `np.array(self.all_samples)` over the **entire** history on every call, then computes Cp, Cpk, Pp, Ppk via four static methods that each do their own full-array `np.mean`/`np.std` pass — roughly **6 full-array passes per call**.
- `get_metrics()` is called **twice per SPC machine per step**: once in `write_machine_opcua_vars` (`src/opcua_server.py:1443`) and again in `collect_step_events` (`src/event_historian.py:542`). For 8 SPC machines that is ~12 growing-array recomputations per second.

**Fix (transparent):**

1. **Welford running aggregates.** Maintain `count`, `mean`, and `M2` incrementally as samples arrive; derive `std = sqrt(M2 / (count - 1))` on demand. Mean/std over the full history are mathematically identical to the batch computation (within floating-point tolerance, see acceptance criteria), so Cp/Cpk/Pp/Ppk values are unchanged. Update and query become O(1) regardless of run length.

```python
class ProcessMonitor:
    def __init__(self, ...):
        ...
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0

    def _update_running_stats(self, x: float) -> None:
        self._n += 1
        delta = x - self._mean
        self._mean += delta / self._n
        self._m2 += delta * (x - self._mean)

    @property
    def _overall_std(self) -> float:
        return math.sqrt(self._m2 / (self._n - 1)) if self._n > 1 else 0.0
```

   `get_metrics()` then computes capability from `self._mean` / `self._overall_std` with **zero** array construction. If `all_samples` has no other consumer (verify with grep before removing), delete it; if something needs raw samples (e.g. a histogram endpoint), keep it behind an explicit opt-in flag rather than always-on.

2. **Single `get_metrics()` call per machine per step.** Compute once in `process_machine_step` (or `write_machine_opcua_vars`), stash the result dict in `machine_metrics[mname]["spc_cached"]`, and have `collect_step_events` read the cached dict instead of recomputing. This mirrors the existing `oee_cached` pattern already used for OEE.

**Files:** `src/spc_analytics.py`, `src/opcua_server.py:1443`, `src/event_historian.py:542`.

### P2 — OPC UA write batching: ~503 lock-acquiring `set_value()` calls per step

**Finding:** For `full_feature_8_machine_line`, one step performs ~503 Python-level `set_value()` invocations:

| Writer | Calls/step |
|---|---|
| `write_machine_opcua_vars` (`src/opcua_server.py:1378-1497`) — 56 per machine × 8 | 448 |
| `write_system_opcua_vars` (1590-1604) | 10 |
| `update_shift_opcua_vars` (1624-1658) | ~28 |
| `update_buffers` (1513) | 7 |
| `update_scrap_tracking` (1552-1558) | 10 |

In the synchronous FreeOpcUa `opcua` library, each server-side `set_value()` acquires the global address-space `RLock`, builds a fresh `DataValue`, and iterates monitored-item callbacks to notify every connected subscriber (Telegraf, web UI, external SCADA clients). Cost per real write scales with subscriber count, and the lock serializes writes against concurrent client reads. `CachedOpcuaNode` already suppresses ~75% of the underlying writes, but all 503 calls plus their comparisons still execute, and the ~125 real writes still take the lock individually.

**Fix (transparent):**

1. **Dirty-set collection.** Change `CachedOpcuaNode.set_value()` so that instead of writing through immediately, it appends `(node, value)` to a per-step `pending_writes` list when the cached comparison says the value changed. All existing dead-band/equality semantics stay exactly as they are.
2. **One batched flush per step.** At the end of the write phase in `run_segment`, issue a single write-many call for the whole dirty set:

```python
# after write_system_opcua_vars / update_shift_opcua_vars
if pending_writes:
    nodes, values = zip(*pending_writes)
    server.set_attributes(     # one lock acquisition, one notification pass
        [n.nodeid for n in nodes],
        [ua.DataValue(ua.Variant(v)) for v in values],
    )
    pending_writes.clear()
```

   The `opcua` library exposes `Server.set_attributes` / `AddressSpace` write-many; verify the exact API of the pinned version and fall back to a single explicit `with server.iserver.aspace._lock:` grouping only if write-many is unavailable.
3. Variant types must be pre-resolved per node (they are known at build time) so the flush loop does no type inference.

**Expected effect:** hundreds of lock acquisitions/notification passes per step collapse to one. Subscribers see identical values with identical timestamps-per-step.

**Files:** `src/opcua_server.py:69-172` (CachedOpcuaNode), `run_segment` write phase.

### P3 — Web UI polling: ~400 serial round-trips every 2 seconds

**Finding:** `_read_opcua_values()` (`docker/webui/app.py:544-670`) navigates the ISA-95 tree with `get_child([...])` per object and `get_value()` per leaf. In the sync client each `get_child` is a `TranslateBrowsePathsToNodeIds` network round-trip and each `get_value` a `Read` round-trip. The machine loop `for i in range(1, 20)` (line 578) does ~20 round-trips per machine and relies on an exception to stop. `/api/status` is polled every 2000 ms (`templates/index.html:1386`); `/graph` and `runs.html` poll every 5000 ms. Result: ~400 serial, blocking round-trips every 2 s, contending for the same address-space lock the sim loop writes under.

**Fix (transparent):**

1. **Resolve once, cache NodeIds.** The browse paths are static for the lifetime of a run. On first successful read (or on run start, keyed by `run_id`), resolve every needed path to a NodeId and store them in a module-level dict. Invalidate the cache when `run_id` changes or a read fails.
2. **One batched read per poll.** Replace the per-leaf `get_value()` calls with a single `client.get_values(cached_nodes)` — one `Read` service call for all ~250 values.
3. **Bound the machine loop by actual machine count.** Read the machine count once (e.g. from the scenario config the UI already has via `/api/scenarios`, or by browsing `Resources` children once at cache-build time) instead of scanning M1–M19 and breaking on exception.

**Expected effect:** per-poll cost drops from ~400 round-trips to 1 (steady state), removing the largest source of lock contention against the simulation loop.

**Files:** `docker/webui/app.py:544-670`.

### P4 — Per-step monkey-patch re-wrapping

**Finding:** Two helpers re-create closures every single step:
- `_install_health_restorer()` (`src/opcua_server.py:2153`, called per machine per step at 2505) redefines and reassigns `machine.initialize` — 8 fresh closures/step.
- `_persist_buffer_state()` (`src/opcua_server.py:2238`, called at 2501) re-wraps every buffer's `initialize` in a fresh closure and snapshots `list(bobj.contents)` — 7 more closures/step.

The patched functions only need re-binding because they capture per-step values (health, repair_remaining, buffer contents) by closure.

**Fix (transparent):** Install each patched `initialize` **once** at segment start; have the closure read its per-step state from a mutable holder that the main loop updates in place:

```python
# segment start — once
holder = {"health": 0, "repair_remaining": 0.0}
machine_state_holders[mname] = holder
original_init = mobj.initialize
def patched_init(self=mobj, _orig=original_init, _h=holder):
    _orig()
    self.health = _h["health"]
    self.under_repair = _h["repair_remaining"] > 0
    ...
mobj.initialize = patched_init

# per step — cheap dict mutation instead of closure re-creation
machine_state_holders[mname]["health"] = machine_health[mname]
machine_state_holders[mname]["repair_remaining"] = machine_repair_remaining[mname]
```

Same pattern for buffer persistence (holder carries the contents snapshot). Simantha's own per-step `initialize()` re-run on ~26 objects remains — that is inherent to the per-step stepping pattern and out of scope here (see Deferred).

**Files:** `src/opcua_server.py:2153-2272`, call sites 2501/2505.

### P5 — O(M²) per-step config scan

**Finding:** `process_machine_step` (`src/opcua_server.py:1253`) does `next(m for m in config_machines if m["name"] == machine_name)` — a linear scan per machine per step.

**Fix:** Build `machine_cfg_by_name = {m["name"]: m for m in config_machines}` once in `run_segment` setup and pass it in.

### P6 — Per-step read of a run-constant

**Finding:** `read_opcua_controls()` (`src/opcua_server.py:1136`, called at 2489) issues a lock-acquiring `get_value()` on `SimSpeedRatio` every step, though the value is fixed at run start (documented read-only since v2.6).

**Fix:** Read once at segment start into a local; delete the per-step call (or keep the function for future writable controls but call it only at segment boundaries).

### P7 — `total_time` computed three times per machine per step

**Finding:** The same five-accumulator sum is recomputed in `process_machine_step` (`src/opcua_server.py:1362`), `write_machine_opcua_vars` (1394), and `collect_step_events` (`src/event_historian.py:482`).

**Fix:** Compute once in `process_machine_step`, store as `metrics["total_time"]`, reuse downstream.

### Deferred (behavior-changing — NOT in scope, recorded for future consideration)

| Option | Why deferred |
|---|---|
| SPC rolling window (`deque(maxlen=N)` for capability) | Changes Cp/Cpk values (window-based instead of full-history). P1's Welford fix removes the need for it. |
| Configurable larger `sim_step` (e.g. 5 s) to amortize Simantha's per-step `initialize()` of ~26 objects | Coarsens event granularity, changes state-transition timing and historian output. |

---

## Part 2 — Deployment Footprint

### D1 — Dependency split and dead weight

**Findings:**
- `requirements.txt` mixes runtime deps with dev tools (`pytest`, `pytest-cov`, `black`, `flake8`) and pins `scikit-learn>=1.3.0` whose **only** consumer is `experiment/detect_anomalies.py:138` — a directory that is *not* COPY'd into the Docker image. scikit-learn and its transitive stack are dead payload in every image build and every CI install.
- `docker/webui/requirements.txt` duplicates `flask`, `pyyaml`, `ruamel.yaml`, `pandas` and **conflicts** with the root file: root pins `flask>=2.3.0`, webui pins `flask>=3.0.0`. The Dockerfile installs both, so the effective floor is 3.0.0 and the root pin is misleading.
- `pandas` is used only in analysis paths (`tools/report_engine.py`, `tools/analyze_historian.py`, one lazy import in `docker/webui/app.py:1450`) — all already behind guarded lazy imports — yet is a hard dependency in both files.

**Spec:**
1. `requirements.txt` → runtime only: `simantha`, `opcua`, `scipy`, `pyyaml`, `ruamel.yaml`, `flask` (single, consistent pin), `paho-mqtt`.
2. New `requirements-dev.txt`: `pytest`, `pytest-cov`, `black`, `flake8` (referenced by CI and CONTRIBUTING docs).
3. New `experiment/requirements.txt`: `scikit-learn>=1.3.0`, `pandas` (documented in `docs/experiments/anomaly_detection_experiment.md`, which currently tells users to install the root file).
4. `pandas` becomes an optional extra documented as `pip install -r requirements-analysis.txt` (or an extras marker if the project ever gains a `pyproject.toml`). The webui CSV-validation endpoint and `tools/` reports already degrade gracefully without it.
5. Delete `docker/webui/requirements.txt` duplication: keep a webui-specific file only if it lists something the root runtime file does not.

### D2 — Dockerfile: multi-stage build, layer consolidation

**Findings:** Single-stage `python:3.10-slim` image; three separate `pip install` layers (lines 13, 17, 18 — the third installs `influxdb-client`/`neo4j` ad hoc, unpinned by any requirements file); dev/test tools baked in via requirements.txt; healthcheck has no `--start-period` so boot-time failures burn retries.

**Spec:**
1. Multi-stage build: builder stage installs the runtime requirements into a venv (`/opt/venv`); final stage `COPY --from=builder /opt/venv /opt/venv` and sets `PATH`. Build toolchain and pip cache never reach the final image.
2. Single `pip install -r requirements.txt -r requirements-optional.txt` layer, where `requirements-optional.txt` pins `influxdb-client` and `neo4j` (currently unpinned inline in the Dockerfile).
3. `HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=30s`.
4. Extend `docker/.dockerignore` with `experiment/`, root-level `*.md`, `docs/` (already present — verify), `config/*_local.yaml`.

**Expected effect:** image sheds scikit-learn's stack, pytest/black/flake8, and builder layers — the dominant size contributors after the base image.

### D3 — Compose profiles (recommended decision point)

**Finding:** `docker/docker-compose.yml` defines **10 services** (`simantha`, `influxdb`, `grafana`, `telegraf`, `neo4j`, `neodash`, `prometheus`, `cadvisor`, `node-exporter`, `mosquitto`) plus 9 volumes, all started unconditionally. The header comment still claims 4 services. `cadvisor` runs `privileged: true` with host mounts; `node-exporter` uses `pid: host`; `neo4j` downloads the APOC plugin on first boot. `simantha` and `grafana` both gate on InfluxDB's healthcheck (up to ~30 s+ before the sim starts).

**Spec (recommended, flagged for owner decision):**
1. Default (no profile): `simantha`, `influxdb`, `grafana`, `telegraf`, `mosquitto`.
2. `profiles: ["graph"]` on `neo4j`, `neodash`.
3. `profiles: ["monitoring"]` on `prometheus`, `cadvisor`, `node-exporter`.
4. Usage: `docker compose --profile graph --profile monitoring up` restores today's full stack; plain `up` gives the documented core.
5. Fix the stale header comment to enumerate services and profiles.

**Expected effect:** default cold-start drops from 10 containers (including a privileged one) to 5; image pulls on a fresh host shrink by neo4j + neodash + prometheus + cadvisor + node-exporter.

### D4 — Stop committing the generated `telegraf.conf`

**Finding:** `docker/telegraf/telegraf.conf` (149,716 bytes) is git-tracked — the single largest file in the repo — yet it is a build artifact: `docker/telegraf/generate_telegraf_conf.py` regenerates it at container start for the active scenario/run_id.

**Spec:** Add `docker/telegraf/telegraf.conf` to `.gitignore`, `git rm --cached` it, and keep only the generator. If a reviewable example is wanted, commit a short `telegraf.conf.example` for a 2-machine scenario instead.

### D5 — CI workflow

**Findings** (`.github/workflows/tests.yml`): 3-version matrix (3.9/3.10/3.11) with no pip caching — every job reinstalls scipy/pandas/scikit-learn wheels from scratch; the test suite runs **twice** per job (plain run, then again under `--cov`); `flake8` and `pytest-cov` are re-installed ad hoc despite being in requirements.

**Spec:**
1. `actions/setup-python@v5` with `cache: 'pip'` (keyed automatically on requirements files).
2. Single test invocation per job: `pytest tests/ -v --cov=src --cov-report=html --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py`.
3. Install `requirements.txt` + `requirements-dev.txt`; delete the ad-hoc `pip install flake8` / `pip install pytest-cov` steps.
4. After D1, CI no longer installs scikit-learn at all.

**Expected effect:** roughly halves per-job test time and removes the wheel-download tax on all 3 matrix jobs.

### D6 — Repo weight notes (informational, owner's call)

- `docs/superpowers/plans/` — ~308 KB of internal planning documents shipped in the repo.
- `docker/webui/templates/docs.html` — 128 KB of embedded documentation HTML.
- Git history itself is healthy: ~580 KiB pack, no binary bloat, `.gitignore` already excludes results/exports correctly.

---

## Part 3 — Scenario/Model Rollout Lifecycle (proposal level)

These formalize how a simulation *model* (scenario + supporting artifacts) is deployed to a target stack, complementing the container-level work above.

### R1 — Scenario bundle packaging

A deployable model today is scattered across `config/line_models.yaml` (one scenario among 25), `config/recipes/*.yaml`, a generated `telegraf.conf`, and Grafana dashboards. Propose `tools/package_scenario.py`:

```bash
python tools/package_scenario.py --scenario full_feature_line \
    --recipes monday_schedule quick_test \
    --output dist/full_feature_line_v1.tar.gz
```

Bundle contents: the single-scenario YAML slice (validated), referenced recipes, a freshly generated `telegraf.conf` for that scenario, the Grafana dashboard JSON, and a `manifest.yaml` (scenario name, schema fields used, generator versions, creation timestamp). The bundle is the unit you hand to a target deployment; the web UI's existing `SIMANTHA_CONFIG_PATH` override is the natural consumption point.

### R2 — Pre-deploy validation CLI

`config_loader.py` already contains the full validator suite (`validate_serial_topology`, `validate_failure_modes`, `validate_historian_config`, …) but it only runs when the server starts. Expose it standalone:

```bash
python -m config_loader --validate full_feature_line          # one scenario
python -m config_loader --validate-all                        # every scenario in the file
```

Exit non-zero on validation failure so it can gate CI and pre-deploy pipelines. Implementation is an `if __name__ == "__main__":` argparse block over existing functions — no new validation logic.

### R3 — NodeSet2 XML export of the address space

`.gitignore` already anticipates `exports/*.xml`. Formalize an export mode so OPC UA clients (FactoryTalk Optix, Ignition, UaExpert) can be configured offline against the exact address space before the simulator is deployed:

```bash
python src/opcua_server.py --scenario full_feature_line --export-nodeset exports/full_feature_line.xml
```

Implementation: build the address space as today, call the `opcua` library's XML exporter over the namespace, and exit without entering the run loop. The export is deterministic per scenario (NodeIds are stable dot-paths), so it can be regenerated in CI and diffed to detect accidental address-space changes — a useful contract test for external integrations.

---

## Part 4 — Acceptance Criteria

### Runtime (Part 1)

| Item | Criterion |
|---|---|
| P1 | Flat RSS over a 2 h `full_feature_8_machine_line` run (RSS at t=2h within 5% of t=10min). Cp/Cpk/Pp/Ppk equal to pre-change values within 1e-9 on `tests/` SPC fixtures. `get_metrics()` wall time independent of run length. |
| P2 | Address-space lock acquired ≤ a small constant number of times per step for writes (instrument with a counting wrapper in a test). All OPC UA values identical per step before/after (golden-run comparison under fixed `--seed`). |
| P3 | `/api/status` handler issues exactly 1 OPC UA `Read` service call in steady state (assert via client instrumentation); p95 latency reported before/after. |
| P4–P7 | Golden-run test: identical historian CSV and identical final OPC UA values for a fixed `--seed`, 600-step run, before vs after. |
| All | Full suite green: `pytest tests/ -v --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py`. |

### Deployment (Part 2)

| Item | Criterion |
|---|---|
| D1/D2 | `docker image ls` size recorded before/after; `pip list` in the final image contains no pytest/black/flake8/scikit-learn. Container serves web UI and runs a scenario end-to-end. |
| D3 | `docker compose up` starts exactly 5 containers; `--profile graph --profile monitoring` restores all 10. |
| D4 | `git ls-files docker/telegraf/` shows only the generator (and optional `.example`); stack still boots (entrypoint regenerates the conf). |
| D5 | CI wall time per matrix job recorded before/after; second and later runs show pip cache hits. |

### Rollout (Part 3)

| Item | Criterion |
|---|---|
| R1 | Bundle extracts onto a clean stack and runs via `SIMANTHA_CONFIG_PATH` pointing at the bundled YAML. |
| R2 | `--validate` exits 0 on all shipped scenarios; exits non-zero with a clear message on a deliberately broken fixture. |
| R3 | Exported XML imports cleanly into UaExpert; re-export of an unchanged scenario is byte-identical (deterministic). |

---

## Suggested Implementation Order

1. **P1** (memory leak + dominant CPU; smallest blast radius, biggest payoff)
2. **P5, P6, P7** (trivial, zero-risk warm-ups that simplify the loop before touching writes)
3. **P2** (write batching — needs the golden-run harness from the acceptance criteria; build that harness first and reuse it for everything)
4. **P3** (web UI batching — independent of server changes, can proceed in parallel)
5. **P4** (patch-once refactor)
6. **D4, D5** (one-line-ish repo/CI wins)
7. **D1, D2** (requirements split, then multi-stage Dockerfile on top of it)
8. **D3** (compose profiles — after owner confirms the profile split)
9. **R2 → R3 → R1** (validation CLI is near-free; NodeSet export enables the bundle to include it later)
