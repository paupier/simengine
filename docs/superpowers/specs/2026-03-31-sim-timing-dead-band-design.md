# Simulation Timing: Dead-Band OPC UA Writes Design

## Goal

Restore 1:1 sim-time to wall-clock accuracy for complex scenarios (8-machine RTF) by eliminating unnecessary OPC UA writes for slowly-changing floating-point metrics, while preserving per-second cause-effect resolution in InfluxDB.

## Background

The 8-machine full-feature RTF scenario takes ~2.5s per loop iteration due to ~480 OPC UA `set_value()` calls per step. Most of these calls write floating-point metrics (OEE components, time accumulators, ActualPPM) that change by a negligible amount each step (e.g., availability: 0.98412 → 0.98413). The `CachedOpcuaNode` wrapper already skips writes on identical values, but floating-point drift means the cache never hits for these continuous metrics.

Result: sim_time falls to ~41% of wall-clock time. A 12-hour run produces only ~5 hours of Grafana data, undermining the project's goal of demonstrating a real-time event-driven architecture.

## Requirements

- After 12 real hours, sim_time ≈ 43200s (1:1 ratio at speed_ratio=1.0)
- InfluxDB retains 1-second wall-clock resolution (Telegraf polls every 1s)
- State transitions and alarm activations are written every step (cause-effect preserved)
- Cause-effect chains (BLOCKED → STARVED cascade) are visible in InfluxDB at 1s resolution
- Speed ratio > 1.0 is supported but visually guarded in the UI

## Architecture

### Component 1: `CachedOpcuaNode` dead-band extension (`src/opcua_server.py`)

Add an optional `dead_band` parameter to `CachedOpcuaNode`. When set, a `set_value()` call is skipped if the new value is within `dead_band` of the last written value.

The current class uses `__slots__ = ("_node", "_cached_value")`. The updated class must change `__slots__` and rename `_cached_value` to `_last_value`:

```python
_UNSET = object()

class CachedOpcuaNode:
    __slots__ = ("_node", "_last_value", "_dead_band")

    def __init__(self, node, dead_band=None):
        self._node = node
        self._last_value = _UNSET
        self._dead_band = dead_band

    def set_value(self, value):
        if self._last_value is _UNSET:
            self._node.set_value(value)
            self._last_value = value
            return
        if self._dead_band is not None:
            try:
                if abs(value - self._last_value) < self._dead_band:
                    return
            except TypeError:
                pass  # non-numeric: fall through to equality check
        if value == self._last_value:
            return
        self._node.set_value(value)
        self._last_value = value

    def get_value(self):
        return self._node.get_value()
```

**Integration with `_wrap_opcua_vars_with_cache()`:**

The existing `_wrap_opcua_vars_with_cache()` bulk-wraps all nodes without dead-band. It must be removed (or bypassed) and replaced by per-node wrapping directly in `build_opcua_server()`. Each node is wrapped individually at creation time with its appropriate dead-band:

```python
# OEE components
var_oee = CachedOpcuaNode(oee_node.add_variable(..., "OEE", 0.0), dead_band=0.001)

# Time accumulators
var_proc_time = CachedOpcuaNode(perf_node.add_variable(..., "ProcessingTime", 0.0), dead_band=1.0)

# Discrete/string — no dead-band
var_state = CachedOpcuaNode(ops_node.add_variable(..., "State", "IDLE"))
```

This replaces the post-build bulk-wrap call entirely.

Dead-band values by node category:

| Node category | Examples | Dead-band |
|---|---|---|
| OEE components (0–1 float) | Availability, Performance, Quality, OEE | `0.001` |
| Time accumulators (float seconds) | ProcessingTime, BlockedTime, StarvedTime, DownTime, IdleTime | `1.0` |
| Failure mode accumulators (float seconds) | `{fm}_downtime`, `{fm}_mtbf`, `{fm}_mttr` per failure mode | `1.0` |
| Throughput rate (float PPM) | ActualPPM | `0.5` |
| Integer/discrete | PartCount, BufferLevel, HealthState, GoodPartCount, DefectivePartCount | None (equality check sufficient) |
| String/bool | State, alarm flags | None (always write on change) |

Note: `SimTime` is **not** assigned a dead-band. With `sim_step = 1.0` (fixed), SimTime increments by exactly 1.0 each step, so a dead-band of 0.5 would always trigger a write anyway — it has no effect and is misleading to include.

Dead-band values are hardcoded by category, not per-scenario YAML config. They reflect meaningful display precision for each metric type.

Expected outcome: effective writes per step drop from ~300 to ~20–40. Each step completes in ~50–80ms, well within the 1s budget.

### Component 2: Revert adaptive sim_step (`src/opcua_server.py`)

The adaptive sim_step introduced in commit `eaea8ca` is reverted. Restore:
- `sim_step = 1.0` (fixed 1 simulated second per step)
- `real_step = 1.0 / max(0.1, min(10.0, speed_ratio))`
- `time.sleep(max(0.0, real_step - elapsed))` pacing

The warm-up guard `sim_time >= warm_up_time` (introduced in `eaea8ca`) is **kept as-is** — with `sim_step = 1.0` fixed, `sim_time` and `step_count` are numerically equivalent after the first step, so there is no functional difference. No change needed for the warm-up logic.

Also revert `opcua_update_interval: 2` from `full_feature_8_machine_line_rtf` in `config/line_models.yaml` (no longer needed).

With dead-band reducing computation to ~80ms/step, sleep handles the remaining ~920ms at speed_ratio=1.0. sim_time advances exactly 1s per step and tracks wall-clock naturally.

### Component 3: UI speed ratio guard (`docker/webui/templates/index.html`)

Add client-side validation and visual feedback on the Sim Speed Ratio input:

- Hard cap: `max="4"` on the HTML input element
- Advisory (yellow) at `> 1.0`: *"Running faster than real-time — Telegraf samples will cover multiple sim-seconds"*
- Warning (orange) at `> 2.0`: *"Cause-effect resolution reduced — state transitions within each Telegraf interval may be missed"*

The 4× cap reflects the practical limit where a 1s Telegraf poll covers 4 sim-seconds of state history. Users needing higher ratios (quick smoke tests) can set `sim_speed` directly in YAML config.

## Data Flow

```
Simantha simulate(1s)           ~20ms
State detection + OEE           ~15ms
Dead-band OPC UA writes         ~50ms  (was ~1000ms, projected not measured)
Historian + MQTT                ~10ms
sleep(remaining budget)         ~905ms
─────────────────────────────────────
Total per step                  ~1000ms  → sim_time = wall_clock ✓
```

Telegraf polls OPC UA every 1s, capturing the state as of the most recently completed step. State transitions (PROCESSING → BLOCKED) written every step appear in InfluxDB at 1s wall-clock resolution. Cause-effect chains that span 2+ seconds are fully visible.

The timing budget above is a projection. A manual smoke test against the `full_feature_8_machine_line_rtf` scenario should confirm actual per-step elapsed time after implementation.

## What Is Not Changing

- `opcua_update_interval` config parameter remains (useful for edge cases / faster hardware)
- `update_buffers()` and `update_scrap_tracking()` `write_opcua` parameter remains
- MQTT publish path unchanged
- Event historian unchanged
- No changes to Telegraf config or poll interval

## Testing

- All 584 existing unit tests must continue to pass
- Unit test: `CachedOpcuaNode.set_value()` skips write when change is within dead-band
- Unit test: `CachedOpcuaNode.set_value()` writes when dead-band threshold is crossed
- Unit test: `CachedOpcuaNode.set_value()` always writes non-numeric (string/bool) values on change
- Unit test: `CachedOpcuaNode` with `dead_band=None` behaves identically to the old implementation
- Integration smoke test: start `full_feature_8_machine_line_rtf`, observe that sim_time advances at ~1s per real second after 60 seconds of runtime
