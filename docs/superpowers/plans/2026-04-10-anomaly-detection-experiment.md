# Anomaly Detection Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add parameterised fault injection to the DES, record a thick per-step CSV alongside the live OPC UA stream, then implement three anomaly detection methods and a ground truth evaluation framework as standalone experiment scripts.

**Architecture:** The OPC UA server runs normally (real-time, 1Hz, Telegraf → InfluxDB unchanged). When `--experiment-mode` is active, two additional outputs are written: a `raw_data.csv` capturing every simulation step's full KPI snapshot, and a `ground_truth.csv` recording each injection event and its eventual failure outcome. Three detection scripts consume `raw_data.csv` and their outputs are evaluated against `ground_truth.csv`. Nothing in the existing runtime path is removed or degraded.

**Tech Stack:** Python 3.11, simantha, opcua, pyyaml, pandas, scikit-learn (new dep), scipy (existing)

---

## File Map

### New files
| Path | Responsibility |
|------|---------------|
| `src/fault_injector.py` | FaultInjection dataclasses, FaultInjector (per-step application logic), GroundTruthWriter |
| `src/experiment_writer.py` | ExperimentWriter — writes thick per-step CSV during experiment mode |
| `experiment/generate_experiment_data.py` | CLI entrypoint: starts OPC UA server subprocess with `--experiment-mode`, waits for completion |
| `experiment/detect_anomalies.py` | Three detection methods against `raw_data.csv` → `detection_results.csv` |
| `experiment/evaluate_results.py` | Precision/recall/lag evaluation against ground truth → `evaluation_report.csv` |
| `experiment/experiment_config.yaml` | Four-anomaly experiment config (seed, scenario, injections, detection params) |
| `experiment/README.md` | Quick-start guide |
| `docs/experiments/anomaly_detection_experiment.md` | Comprehensive experiment documentation |

### Modified files
| Path | Changes |
|------|---------|
| `requirements.txt` | Add `scikit-learn>=1.3.0` |
| `src/config_loader.py` | Add `validate_fault_injection(config)` called from `validate_serial_topology()` |
| `src/opcua_server.py` | `metrics` init: add `spc_noise_scale`, `h_max`, `spc_target_cycle_time`; `write_machine_opcua_vars()`: noise scaling; `run_segment()`: FaultInjector + ExperimentWriter integration; `main()`: `--experiment-mode`, `--experiment-output` flags |
| `config/line_models.yaml` | Add `anomaly_detection_experiment` scenario |

---

## Task 1: Add scikit-learn dependency

**Files:**
- Modify: `requirements.txt`
- Modify: `docs/experiments/anomaly_detection_experiment.md` (create stub)

- [ ] **Step 1: Add scikit-learn to requirements.txt**

```
scikit-learn>=1.3.0
```

- [ ] **Step 2: Verify install**

```bash
pip install scikit-learn>=1.3.0
python -c "from sklearn.ensemble import IsolationForest; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Create documentation stub**

Create `docs/experiments/anomaly_detection_experiment.md` with only a `# Anomaly Detection Experiment` heading. Content is filled in Task 10.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt docs/experiments/anomaly_detection_experiment.md
git commit -m "feat: add scikit-learn dep and experiment docs stub"
```

---

## Task 2: FaultInjection config schema + validation

**Files:**
- Modify: `src/config_loader.py` — add `validate_fault_injection()`
- Test: `tests/test_fault_injector.py` — create with config validation tests

The `fault_injection` block lives at the scenario top level (not per-machine):

```yaml
fault_injection:
  spc_noise_scale: 2.0          # CV multiplier per health unit (fraction of h_max)
                                 # 0.0 = disabled. Applied in addition to base noise.
  injections:
    - type: health_delta
      machine: M1
      at_sim_time: 1500
      health_delta: 2
    - type: noise_ramp
      machine: M2
      at_sim_time: 2000
      duration: 200
      target_multiplier: 2.5    # noise_cv → noise_cv * 2.5 over 200 steps
    - type: cycle_time_offset
      machine: M4
      at_sim_time: 3000
      offset: 0.3               # nominal cycle time shifts +0.3s for SPC measurements
```

- [ ] **Step 1: Write failing config validation tests**

```python
# tests/test_fault_injector.py
import pytest
from config_loader import validate_fault_injection

def test_empty_fault_injection_is_valid():
    validate_fault_injection({})  # no fault_injection key → no error

def test_valid_health_delta_injection():
    cfg = {"fault_injection": {
        "spc_noise_scale": 2.0,
        "injections": [
            {"type": "health_delta", "machine": "M1",
             "at_sim_time": 1500, "health_delta": 2}
        ]
    }}
    validate_fault_injection(cfg)  # must not raise

def test_valid_noise_ramp_injection():
    cfg = {"fault_injection": {"spc_noise_scale": 1.0, "injections": [
        {"type": "noise_ramp", "machine": "M2", "at_sim_time": 2000,
         "duration": 200, "target_multiplier": 2.5}
    ]}}
    validate_fault_injection(cfg)

def test_valid_cycle_time_offset_injection():
    cfg = {"fault_injection": {"injections": [
        {"type": "cycle_time_offset", "machine": "M4",
         "at_sim_time": 3000, "offset": 0.3}
    ]}}
    validate_fault_injection(cfg)

def test_unknown_injection_type_raises():
    cfg = {"fault_injection": {"injections": [
        {"type": "teleport", "machine": "M1", "at_sim_time": 100}
    ]}}
    with pytest.raises(ValueError, match="Unknown injection type"):
        validate_fault_injection(cfg)

def test_health_delta_missing_machine_raises():
    cfg = {"fault_injection": {"injections": [
        {"type": "health_delta", "at_sim_time": 100, "health_delta": 1}
    ]}}
    with pytest.raises(ValueError, match="machine"):
        validate_fault_injection(cfg)

def test_noise_ramp_missing_duration_raises():
    cfg = {"fault_injection": {"injections": [
        {"type": "noise_ramp", "machine": "M1", "at_sim_time": 100,
         "target_multiplier": 2.0}
    ]}}
    with pytest.raises(ValueError, match="duration"):
        validate_fault_injection(cfg)

def test_spc_noise_scale_negative_raises():
    cfg = {"fault_injection": {"spc_noise_scale": -1.0, "injections": []}}
    with pytest.raises(ValueError, match="spc_noise_scale"):
        validate_fault_injection(cfg)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_fault_injector.py -v
```
Expected: ImportError or AttributeError on `validate_fault_injection`

- [ ] **Step 3: Implement `validate_fault_injection` in `config_loader.py`**

Add after the existing validate functions:

```python
def validate_fault_injection(config: Dict[str, Any]) -> None:
    """Validate the optional fault_injection block at scenario level."""
    fi = config.get("fault_injection")
    if fi is None:
        return

    scale = fi.get("spc_noise_scale", 0.0)
    if not isinstance(scale, (int, float)) or scale < 0:
        raise ValueError(
            f"fault_injection.spc_noise_scale must be a non-negative number, got {scale!r}"
        )

    REQUIRED_FIELDS = {
        "health_delta":      ["machine", "at_sim_time", "health_delta"],
        "noise_ramp":        ["machine", "at_sim_time", "duration", "target_multiplier"],
        "cycle_time_offset": ["machine", "at_sim_time", "offset"],
    }

    for i, inj in enumerate(fi.get("injections", [])):
        t = inj.get("type")
        if t not in REQUIRED_FIELDS:
            raise ValueError(
                f"fault_injection.injections[{i}]: Unknown injection type {t!r}. "
                f"Valid types: {list(REQUIRED_FIELDS)}"
            )
        for field in REQUIRED_FIELDS[t]:
            if field not in inj:
                raise ValueError(
                    f"fault_injection.injections[{i}] (type={t!r}): "
                    f"missing required field '{field}'"
                )
```

Add `validate_fault_injection(config)` call inside `validate_serial_topology()` just before the final print statement.

Also export `validate_fault_injection` in `config_loader.py`'s top-level (it's already importable by function name).

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_fault_injector.py -v
```
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/config_loader.py tests/test_fault_injector.py
git commit -m "feat: add fault_injection config schema and validation"
```

---

## Task 3: FaultInjector class + GroundTruthWriter

**Files:**
- Create: `src/fault_injector.py`
- Test: `tests/test_fault_injector.py` — add FaultInjector unit tests

- [ ] **Step 1: Write failing tests for FaultInjector**

```python
# append to tests/test_fault_injector.py
import os, csv, tempfile
from fault_injector import FaultInjector, GroundTruthWriter

# --- FaultInjector: health_delta ---

def test_health_delta_fires_at_correct_time():
    injector = FaultInjector([
        {"type": "health_delta", "machine": "M1", "at_sim_time": 500, "health_delta": 2}
    ])
    machine_health = {"M1": 0}
    machine_metrics = {"M1": {"h_max": 4}}
    # Before injection time — no change
    injector.step(499.0, machine_health, machine_metrics)
    assert machine_health["M1"] == 0
    # At injection time — fires
    fired = injector.step(500.0, machine_health, machine_metrics)
    assert machine_health["M1"] == 2
    assert len(fired) == 1
    assert fired[0]["type"] == "health_delta"

def test_health_delta_clamped_to_h_max():
    injector = FaultInjector([
        {"type": "health_delta", "machine": "M1", "at_sim_time": 100, "health_delta": 10}
    ])
    machine_health = {"M1": 2}
    machine_metrics = {"M1": {"h_max": 4}}
    injector.step(100.0, machine_health, machine_metrics)
    assert machine_health["M1"] == 4  # clamped

def test_health_delta_fires_only_once():
    injector = FaultInjector([
        {"type": "health_delta", "machine": "M1", "at_sim_time": 100, "health_delta": 1}
    ])
    machine_health = {"M1": 0}
    machine_metrics = {"M1": {"h_max": 4}}
    injector.step(100.0, machine_health, machine_metrics)
    machine_health["M1"] = 0  # reset externally
    fired = injector.step(101.0, machine_health, machine_metrics)
    assert len(fired) == 0  # does not re-fire

# --- FaultInjector: noise_ramp ---

def test_noise_ramp_starts_at_injection_time():
    injector = FaultInjector([
        {"type": "noise_ramp", "machine": "M2", "at_sim_time": 200,
         "duration": 100, "target_multiplier": 3.0}
    ])
    metrics = {"M2": {"spc_measurement_noise": 0.02, "h_max": 4}}
    # Before ramp
    injector.step(199.0, {}, metrics)
    assert metrics["M2"]["spc_measurement_noise"] == 0.02
    # At start of ramp (progress=0, noise unchanged)
    injector.step(200.0, {}, metrics)
    assert metrics["M2"]["spc_measurement_noise"] == pytest.approx(0.02, abs=1e-6)
    # Midpoint (progress=0.5, noise = 0.02 * (1 + 0.5*(3-1)) = 0.04)
    injector.step(250.0, {}, metrics)
    assert metrics["M2"]["spc_measurement_noise"] == pytest.approx(0.04, abs=1e-4)
    # At end (progress=1.0, noise = 0.02 * 3.0 = 0.06)
    injector.step(300.0, {}, metrics)
    assert metrics["M2"]["spc_measurement_noise"] == pytest.approx(0.06, abs=1e-4)

# --- FaultInjector: cycle_time_offset ---

def test_cycle_time_offset_sets_spc_target():
    injector = FaultInjector([
        {"type": "cycle_time_offset", "machine": "M4", "at_sim_time": 1000, "offset": 0.3}
    ])
    metrics = {"M4": {"cycle_time": 1.1, "h_max": 5}}
    injector.step(1000.0, {}, metrics)
    assert metrics["M4"].get("spc_target_cycle_time") == pytest.approx(1.4, abs=1e-6)

def test_cycle_time_offset_does_not_change_actual_cycle_time():
    injector = FaultInjector([
        {"type": "cycle_time_offset", "machine": "M4", "at_sim_time": 100, "offset": 0.3}
    ])
    metrics = {"M4": {"cycle_time": 1.1, "h_max": 5}}
    injector.step(100.0, {}, metrics)
    assert metrics["M4"]["cycle_time"] == pytest.approx(1.1, abs=1e-6)  # unchanged

# --- GroundTruthWriter ---

def test_ground_truth_writer_creates_csv():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ground_truth.csv")
        writer = GroundTruthWriter(path, run_id="test_run")
        writer.record_injection({
            "type": "health_delta", "machine": "M1",
            "injection_sim_time": 500.0, "health_before": 0, "health_after": 2,
            "h_max": 4,
        })
        writer.close()
        with open(path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["machine"] == "M1"
        assert rows[0]["injection_sim_time"] == "500.0"

def test_ground_truth_writer_updates_failure_time():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ground_truth.csv")
        writer = GroundTruthWriter(path, run_id="test_run")
        writer.record_injection({
            "type": "health_delta", "machine": "M1",
            "injection_sim_time": 500.0, "health_before": 0, "health_after": 2,
            "h_max": 4,
        })
        writer.notify_failure("M1", sim_time=650.0)
        writer.notify_repair_complete("M1", sim_time=670.0)
        writer.close()
        with open(path) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["failure_sim_time"] == "650.0"
        assert rows[0]["repair_complete_sim_time"] == "670.0"
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
pytest tests/test_fault_injector.py -v -k "FaultInjector or GroundTruth"
```
Expected: ImportError on `fault_injector`

- [ ] **Step 3: Create `src/fault_injector.py`**

```python
"""
Fault injection engine for anomaly detection experiments.

Applies parameterised degradation events at specific simulation times,
layered on top of the existing stochastic Markov-chain degradation.
Writes ground truth labels as a side effect, tracking injection times
and subsequent failure/repair events.

Three injection types:
  health_delta      — step jump in Markov health state
  noise_ramp        — linearly increases SPC measurement noise CV over N steps
  cycle_time_offset — shifts the nominal cycle time used for SPC measurements
"""
import csv
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Injection dataclasses
# ---------------------------------------------------------------------------

@dataclass
class _HealthDelta:
    machine: str
    at_sim_time: float
    health_delta: int
    _fired: bool = field(default=False, repr=False)


@dataclass
class _NoiseRamp:
    machine: str
    at_sim_time: float
    duration: float
    target_multiplier: float
    _fired: bool = field(default=False, repr=False)
    _initial_noise: float = field(default=0.0, repr=False)


@dataclass
class _CycleTimeOffset:
    machine: str
    at_sim_time: float
    offset: float
    _fired: bool = field(default=False, repr=False)


# ---------------------------------------------------------------------------
# FaultInjector
# ---------------------------------------------------------------------------

class FaultInjector:
    """
    Checks and applies fault injections each simulation step.

    Call ``step()`` once per sim step immediately after system.simulate()
    returns and before process_machine_step() runs.  Mutations are applied
    directly to ``machine_health`` and ``machine_metrics`` dicts that the
    main loop already owns, so no additional wiring is needed.
    """

    def __init__(self, injections_config: list, spc_noise_scale: float = 0.0):
        """
        Args:
            injections_config: List of injection dicts from scenario YAML.
            spc_noise_scale: Scenario-level health-correlated noise multiplier.
                             Stored here for access by the main loop; actual
                             application happens in write_machine_opcua_vars().
        """
        self.spc_noise_scale = spc_noise_scale
        self._health_deltas: List[_HealthDelta] = []
        self._noise_ramps: List[_NoiseRamp] = []
        self._cycle_offsets: List[_CycleTimeOffset] = []

        for inj in injections_config:
            t = inj.get("type", "health_delta")
            if t == "health_delta":
                self._health_deltas.append(_HealthDelta(
                    machine=inj["machine"],
                    at_sim_time=float(inj["at_sim_time"]),
                    health_delta=int(inj["health_delta"]),
                ))
            elif t == "noise_ramp":
                self._noise_ramps.append(_NoiseRamp(
                    machine=inj["machine"],
                    at_sim_time=float(inj["at_sim_time"]),
                    duration=float(inj["duration"]),
                    target_multiplier=float(inj["target_multiplier"]),
                ))
            elif t == "cycle_time_offset":
                self._cycle_offsets.append(_CycleTimeOffset(
                    machine=inj["machine"],
                    at_sim_time=float(inj["at_sim_time"]),
                    offset=float(inj["offset"]),
                ))

    def step(
        self,
        sim_time: float,
        machine_health: Dict[str, int],
        machine_metrics: Dict[str, dict],
    ) -> List[dict]:
        """
        Apply all due injections and return records for newly fired ones.

        Returns:
            List of dicts, one per newly fired injection, for the ground
            truth writer.  Empty list if nothing fired this step.
        """
        fired = []

        # health_delta: one-shot at at_sim_time
        for inj in self._health_deltas:
            if not inj._fired and sim_time >= inj.at_sim_time:
                inj._fired = True
                prev = machine_health.get(inj.machine, 0)
                h_max = machine_metrics.get(inj.machine, {}).get("h_max", 1)
                new_health = min(prev + inj.health_delta, h_max)
                machine_health[inj.machine] = new_health
                fired.append({
                    "type": "health_delta",
                    "machine": inj.machine,
                    "injection_sim_time": sim_time,
                    "health_before": prev,
                    "health_after": new_health,
                    "h_max": h_max,
                    "failure_sim_time": None,
                    "repair_complete_sim_time": None,
                })

        # noise_ramp: fires once, then updates noise each step during ramp
        for inj in self._noise_ramps:
            if sim_time < inj.at_sim_time:
                continue
            metrics = machine_metrics.get(inj.machine)
            if metrics is None:
                continue
            if not inj._fired:
                inj._fired = True
                inj._initial_noise = metrics.get("spc_measurement_noise", 0.02)
                fired.append({
                    "type": "noise_ramp",
                    "machine": inj.machine,
                    "injection_sim_time": sim_time,
                    "duration": inj.duration,
                    "target_multiplier": inj.target_multiplier,
                    "initial_noise": inj._initial_noise,
                    "failure_sim_time": None,
                    "repair_complete_sim_time": None,
                })
            elapsed = sim_time - inj.at_sim_time
            if elapsed <= inj.duration:
                progress = elapsed / inj.duration
                # Linear interpolation: noise_cv × (1 + progress × (mult − 1))
                new_noise = inj._initial_noise * (1.0 + progress * (inj.target_multiplier - 1.0))
                metrics["spc_measurement_noise"] = new_noise

        # cycle_time_offset: one-shot, sets spc_target_cycle_time permanently
        for inj in self._cycle_offsets:
            if not inj._fired and sim_time >= inj.at_sim_time:
                inj._fired = True
                metrics = machine_metrics.get(inj.machine, {})
                original = metrics.get("cycle_time", 1.0)
                metrics["spc_target_cycle_time"] = original + inj.offset
                fired.append({
                    "type": "cycle_time_offset",
                    "machine": inj.machine,
                    "injection_sim_time": sim_time,
                    "original_cycle_time": original,
                    "offset": inj.offset,
                    "failure_sim_time": None,
                    "repair_complete_sim_time": None,
                })

        return fired

    def notify_failure(self, machine: str, sim_time: float) -> None:
        """Record the first failure time after a health_delta injection."""
        # Update the most recent unfilled health_delta record for this machine
        # (tracked by GroundTruthWriter — called through it)
        pass

    def notify_repair_complete(self, machine: str, sim_time: float) -> None:
        """Record repair completion time."""
        pass


# ---------------------------------------------------------------------------
# GroundTruthWriter
# ---------------------------------------------------------------------------

_GT_COLUMNS = [
    "run_id", "type", "machine",
    "injection_sim_time", "health_before", "health_after", "h_max",
    "initial_noise", "target_multiplier", "duration",
    "original_cycle_time", "offset",
    "failure_sim_time", "repair_complete_sim_time",
    "anomaly_window_start", "anomaly_window_end",
]


class GroundTruthWriter:
    """
    Writes ground truth injection records to a CSV file.

    Records are written immediately when an injection fires.  Subsequent
    calls to notify_failure() and notify_repair_complete() fill in the
    failure and repair timestamps for the most recent health_delta injection
    on that machine (which defines the anomaly window end).

    The anomaly window is defined as:
      - health_delta:      [injection_sim_time, repair_complete_sim_time]
      - noise_ramp:        [injection_sim_time, injection_sim_time + duration]
      - cycle_time_offset: [injection_sim_time, end_of_run (left blank)]
    """

    def __init__(self, path: str, run_id: str):
        self._path = path
        self._run_id = run_id
        self._records: List[dict] = []   # in-memory; flushed on close()
        # Track pending health_delta records per machine (for failure updates)
        self._pending_health: Dict[str, dict] = {}

    def record_injection(self, record: dict) -> None:
        """Add a fired injection record. Called by FaultInjector.step() results."""
        row = {col: "" for col in _GT_COLUMNS}
        row["run_id"] = self._run_id
        row.update({k: v for k, v in record.items() if k in row})
        # Compute known anomaly window bounds
        t = record.get("type")
        start = record.get("injection_sim_time", "")
        row["anomaly_window_start"] = start
        if t == "noise_ramp":
            row["anomaly_window_end"] = float(start) + float(record.get("duration", 0))
        # health_delta and cycle_time_offset: end filled later or left blank
        self._records.append(row)
        if t == "health_delta":
            self._pending_health[record["machine"]] = row

    def notify_failure(self, machine: str, sim_time: float) -> None:
        """Fill failure_sim_time for the pending health_delta on this machine."""
        row = self._pending_health.get(machine)
        if row and not row.get("failure_sim_time"):
            row["failure_sim_time"] = sim_time

    def notify_repair_complete(self, machine: str, sim_time: float) -> None:
        """Fill repair_complete_sim_time and close the anomaly window."""
        row = self._pending_health.get(machine)
        if row and not row.get("repair_complete_sim_time"):
            row["repair_complete_sim_time"] = sim_time
            row["anomaly_window_end"] = sim_time
            # Clear pending — next failure starts a new record
            del self._pending_health[machine]

    def close(self) -> None:
        """Write all records to CSV. Safe to call even if no injections fired."""
        with open(self._path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_GT_COLUMNS)
            writer.writeheader()
            writer.writerows(self._records)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_fault_injector.py -v
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/fault_injector.py tests/test_fault_injector.py
git commit -m "feat: add FaultInjector class and GroundTruthWriter"
```

---

## Task 4: noise_scale_per_health in SPC measurement

**Files:**
- Modify: `src/opcua_server.py` — `machine_metrics` init, `write_machine_opcua_vars()` SPC noise block

The scenario-level `spc_noise_scale` stored in `metrics["spc_noise_scale"]` scales the SPC measurement noise proportionally to how degraded the machine is: `noise_cv_eff = noise_cv * (1 + scale * health_state / h_max)`. At health=0 there is no change; at health=h_max noise is fully scaled.

`h_max` is `getattr(machine_obj, 'failed_health', 1)` — already accessible inside `write_machine_opcua_vars()` via the `machine_obj` parameter.

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_new_features.py
class TestSPCNoiseScalePerHealth:
    """noise_scale_per_health increases SPC measurement noise with health state."""

    def _call_with_health(self, health_state, noise_scale, h_max=4, base_noise=0.02):
        machine, metrics, config_machines, opcua_vars, sink, total_parts = \
            _make_process_step_args(cycle_time=1.0, prev_state="PROCESSING",
                                    parts_made=1, total_parts=6, prev_partcount=5)
        machine.health = health_state
        machine.failed_health = h_max
        metrics["spc_measurement_noise"] = base_noise
        metrics["spc_noise_scale"] = noise_scale
        metrics["h_max"] = h_max

        measurements = []
        spc_monitor = MagicMock()
        spc_monitor.get_metrics.return_value = _make_spc_result(in_control=True)
        spc_monitor.add_measurement.side_effect = lambda m: measurements.append(m)

        process_machine_step(
            "M1", machine, metrics, config_machines,
            6, 1.0, None, None, {"M1": spc_monitor}, opcua_vars, sink, 10.0,
            write_opcua=True
        )
        return measurements

    def test_no_scale_uses_base_noise(self):
        """With spc_noise_scale=0, noise_cv is unchanged regardless of health."""
        import random; random.seed(42)
        measurements = self._call_with_health(health_state=3, noise_scale=0.0)
        # Can only verify measurement is close to cycle_time (1.0)
        assert len(measurements) == 1
        assert 0.9 < measurements[0] < 1.1  # within ±10% is fine

    def test_full_health_scale_increases_variance(self):
        """At health=h_max with scale=2.0, effective CV = base*(1+2.0) = 3x."""
        import random, statistics
        random.seed(42)
        # Collect many measurements to check variance increases
        all_m_low = []
        all_m_high = []
        for _ in range(100):
            all_m_low  += self._call_with_health(health_state=0, noise_scale=2.0)
            all_m_high += self._call_with_health(health_state=4, noise_scale=2.0)
        assert statistics.stdev(all_m_high) > statistics.stdev(all_m_low) * 1.5

    def test_zero_health_no_scaling(self):
        """At health=0, noise_cv is always unchanged regardless of noise_scale."""
        import random; random.seed(0)
        # With any scale, health=0 → divisor is 0/h_max=0 → no change
        m_no_scale  = self._call_with_health(health_state=0, noise_scale=0.0)
        m_has_scale = self._call_with_health(health_state=0, noise_scale=3.0)
        # Both use same seed → same measurement
        assert m_no_scale == m_has_scale
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
pytest tests/test_new_features.py::TestSPCNoiseScalePerHealth -v
```
Expected: FAIL — `spc_noise_scale` key not found in metrics

- [ ] **Step 3: Add `spc_noise_scale` and `h_max` to metrics init in `run_segment()`**

In the `machine_metrics[machine_name] = {...}` block (around line 2309), add two entries:

```python
"spc_noise_scale": config.get("fault_injection", {}).get("spc_noise_scale", 0.0),
"h_max": 1,  # overwritten below when enable_degradation=True
```

Then after the `if enable_degradation:` block that reads `health_states`, add:
```python
if enable_degradation and health_cfg:
    machine_metrics[machine_name]["h_max"] = health_cfg.get("h_max", 1)
```

- [ ] **Step 4: Apply noise scaling in `write_machine_opcua_vars()`**

In the SPC section, replace:
```python
noise_cv = metrics.get("spc_measurement_noise", 0.02)
measurement = metrics["cycle_time"] * (1.0 + random.gauss(0, noise_cv))
```

With:
```python
noise_cv = metrics.get("spc_measurement_noise", 0.02)
_noise_scale = metrics.get("spc_noise_scale", 0.0)
if _noise_scale > 0.0 and health_state > 0:
    _h_max = getattr(machine_obj, 'failed_health', 1)
    if _h_max > 0:
        noise_cv = noise_cv * (1.0 + _noise_scale * health_state / _h_max)
# SPC measurement: use spc_target_cycle_time if set (cycle_time_offset injection)
_spc_cycle = metrics.get("spc_target_cycle_time", metrics["cycle_time"])
measurement = _spc_cycle * (1.0 + random.gauss(0, noise_cv))
```

This also wires in `spc_target_cycle_time` for the `cycle_time_offset` injection type.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_new_features.py::TestSPCNoiseScalePerHealth -v
pytest tests/test_new_features.py -q  # regression check
```
Expected: new tests PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/opcua_server.py tests/test_new_features.py
git commit -m "feat: health-correlated SPC noise scaling and cycle_time_offset SPC target"
```

---

## Task 5: FaultInjector integration in `run_segment()`

**Files:**
- Modify: `src/opcua_server.py` — `run_segment()` signature, per-step injection, failure/repair notifications
- Modify: `src/opcua_server.py` — `main()` to build FaultInjector from config and pass it in

The FaultInjector is built from `config.get("fault_injection", {})` before `run_segment()` is called, then passed as an optional `fault_injector=None` parameter.

- [ ] **Step 1: Add `fault_injector` parameter to `run_segment()` signature**

```python
def run_segment(
    ...,
    mqtt_publisher=None,
    fault_injector=None,   # ← new, default None for backward compat
):
```

- [ ] **Step 2: Add per-step injection call inside `run_segment()` main loop**

Immediately after `line_state.sync_machine()` / `line_state.sync_sink()` (around line 2524), add:

```python
# Fault injection (experiment mode only — no-op when fault_injector is None)
if fault_injector is not None:
    fired = fault_injector.step(sim_time, machine_health, machine_metrics)
    if fired and gt_writer is not None:
        for record in fired:
            gt_writer.record_injection(record)
```

`gt_writer` is the `GroundTruthWriter` instance, introduced in Task 6.

- [ ] **Step 3: Add failure/repair notifications**

In the repair countdown block (around line 2484 where `machine_repair_remaining` reaches 0), add:

```python
# Notify fault injector when failure first occurs
if machine_repair_remaining[mname] > 0 and prev_repair == 0:
    if fault_injector is not None and gt_writer is not None:
        gt_writer.notify_failure(mname, sim_time)

# Notify fault injector when repair completes
if prev_repair > 0 and machine_repair_remaining[mname] == 0.0:
    if fault_injector is not None and gt_writer is not None:
        gt_writer.notify_repair_complete(mname, sim_time)
```

Store `prev_repair = machine_repair_remaining[mname]` before the countdown block.

- [ ] **Step 4: Wire FaultInjector into `main()`**

```python
from fault_injector import FaultInjector

# After loading config, before build_simantha_system():
fi_cfg = config.get("fault_injection", {})
fault_injector = FaultInjector(
    injections_config=fi_cfg.get("injections", []),
    spc_noise_scale=fi_cfg.get("spc_noise_scale", 0.0),
) if fi_cfg.get("injections") else None
```

Pass `fault_injector=fault_injector` to `run_segment()`.

- [ ] **Step 5: Also update `spc_noise_scale` in metrics from FaultInjector**

When `fault_injector` is not None, after building `machine_metrics`:
```python
if fault_injector is not None:
    for mname in machines:
        machine_metrics[mname]["spc_noise_scale"] = fault_injector.spc_noise_scale
```

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -q --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/opcua_server.py
git commit -m "feat: integrate FaultInjector into run_segment()"
```

---

## Task 6: ExperimentWriter (thick per-step CSV)

**Files:**
- Create: `src/experiment_writer.py`
- Modify: `src/opcua_server.py` — `run_segment()` + `main()` `--experiment-mode` and `--experiment-output` flags

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_fault_injector.py
from experiment_writer import ExperimentWriter
from unittest.mock import MagicMock

def _make_mock_buffers(names):
    return {n: MagicMock(level=5) for n in names}

def test_experiment_writer_creates_csv_with_header():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "raw_data.csv")
        writer = ExperimentWriter(path, ["M1", "M2"], ["B1"])
        writer.close()
        with open(path) as f:
            header = f.readline().strip().split(",")
        assert "sim_time" in header
        assert "M1_State" in header
        assert "M2_SPC_Cpk" in header
        assert "B1_Level" in header

def test_experiment_writer_writes_one_row_per_step():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "raw_data.csv")
        writer = ExperimentWriter(path, ["M1"], ["B1"])
        machine_metrics = {"M1": {
            "prev_state": "PROCESSING", "oee_cached": {"oee": 0.85, "availability": 0.9},
            "processing_time": 10.0, "starved_time": 2.0,
            "blocked_time": 0.0, "down_time": 0.0,
            "spc_cumulative_ooc": 0,
        }}
        machine_health = {"M1": 1}
        spc_monitor = MagicMock()
        spc_monitor.get_metrics.return_value = _make_spc_result(in_control=True)
        buffers = _make_mock_buffers(["B1"])
        writer.write_step(100.0, "run_01", machine_metrics, machine_health,
                          {"M1": spc_monitor}, buffers)
        writer.close()
        with open(path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["M1_State"] == "PROCESSING"
        assert rows[0]["M1_HealthState"] == "1"
        assert float(rows[0]["M1_OEE"]) == pytest.approx(0.85, abs=0.001)
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
pytest tests/test_fault_injector.py -v -k "experiment_writer"
```
Expected: ImportError

- [ ] **Step 3: Create `src/experiment_writer.py`**

```python
"""
ExperimentWriter: records a full KPI snapshot every simulation step to CSV.

This is the "thick CSV" output for the anomaly detection experiment.  It
runs alongside the live OPC UA publish path — the same computed values that
just went to OPC UA are written here, providing an analysis-friendly flat
file without requiring InfluxDB queries.

Enabled only when the server is started with --experiment-mode.
"""
import csv
from typing import Dict, List, Optional


class ExperimentWriter:
    """Write one CSV row per simulation step containing all machine and buffer KPIs."""

    def __init__(self, path: str, machine_names: List[str], buffer_names: List[str]):
        self._machine_names = list(machine_names)
        self._buffer_names = list(buffer_names)
        self._columns = self._build_columns()
        self._file = open(path, "w", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=self._columns,
                                      extrasaction="ignore")
        self._writer.writeheader()

    def _build_columns(self) -> List[str]:
        cols = ["sim_time", "run_id"]
        for m in self._machine_names:
            cols += [
                f"{m}_State", f"{m}_HealthState",
                f"{m}_OEE", f"{m}_Availability",
                f"{m}_ProcessingTime", f"{m}_StarvedTime",
                f"{m}_BlockedTime", f"{m}_DownTime",
                f"{m}_SPC_XBar", f"{m}_SPC_Cpk", f"{m}_SPC_CumulativeOOC",
            ]
        for b in self._buffer_names:
            cols.append(f"{b}_Level")
        return cols

    def write_step(
        self,
        sim_time: float,
        run_id: str,
        machine_metrics: Dict[str, dict],
        machine_health: Dict[str, int],
        spc_monitors: dict,
        buffers: dict,
    ) -> None:
        row: dict = {"sim_time": sim_time, "run_id": run_id}

        for m in self._machine_names:
            metrics = machine_metrics.get(m, {})
            oee = metrics.get("oee_cached") or {}
            row[f"{m}_State"]          = metrics.get("prev_state", "IDLE")
            row[f"{m}_HealthState"]    = machine_health.get(m, 0)
            row[f"{m}_OEE"]            = round(oee.get("oee", 0.0), 4)
            row[f"{m}_Availability"]   = round(oee.get("availability", 0.0), 4)
            row[f"{m}_ProcessingTime"] = round(metrics.get("processing_time", 0.0), 1)
            row[f"{m}_StarvedTime"]    = round(metrics.get("starved_time", 0.0), 1)
            row[f"{m}_BlockedTime"]    = round(metrics.get("blocked_time", 0.0), 1)
            row[f"{m}_DownTime"]       = round(metrics.get("down_time", 0.0), 1)
            spc = spc_monitors.get(m)
            if spc is not None:
                try:
                    sm = spc.get_metrics()
                    row[f"{m}_SPC_XBar"] = round(sm.x_bar, 4)
                    row[f"{m}_SPC_Cpk"]  = round(sm.cpk, 4)
                except Exception:
                    row[f"{m}_SPC_XBar"] = 0.0
                    row[f"{m}_SPC_Cpk"]  = 0.0
            else:
                row[f"{m}_SPC_XBar"] = 0.0
                row[f"{m}_SPC_Cpk"]  = 0.0
            row[f"{m}_SPC_CumulativeOOC"] = metrics.get("spc_cumulative_ooc", 0)

        for b, bobj in buffers.items():
            row[f"{b}_Level"] = bobj.level

        self._writer.writerow(row)

    def close(self) -> None:
        """Flush and close the output file."""
        self._file.flush()
        self._file.close()
```

- [ ] **Step 4: Add `--experiment-mode` and `--experiment-output` flags to `main()`**

```python
parser.add_argument("--experiment-mode", action="store_true", dest="experiment_mode",
                    help="Enable experiment thick-CSV and ground-truth writers")
parser.add_argument("--experiment-output", default="experiment/results",
                    dest="experiment_output",
                    help="Directory for raw_data.csv and ground_truth.csv output")
```

In `main()`, after building `run_id`, create writers if experiment mode:
```python
exp_writer = None
gt_writer = None
if args.experiment_mode:
    import os
    from experiment_writer import ExperimentWriter
    from fault_injector import GroundTruthWriter
    os.makedirs(args.experiment_output, exist_ok=True)
    raw_path = os.path.join(args.experiment_output, f"{run_id}_raw_data.csv")
    gt_path  = os.path.join(args.experiment_output, f"{run_id}_ground_truth.csv")
    machine_names = [m["name"] for m in config["machines"]]
    buffer_names  = [b["name"] for b in config["buffers"]]
    exp_writer = ExperimentWriter(raw_path, machine_names, buffer_names)
    gt_writer  = GroundTruthWriter(gt_path, run_id=run_id)
    print(f"[experiment] raw_data  → {raw_path}")
    print(f"[experiment] ground_truth → {gt_path}")
```

Pass both to `run_segment()`:
```python
def run_segment(..., fault_injector=None, exp_writer=None, gt_writer=None):
```

Inside the main loop, after all `process_machine_step()` calls, add:
```python
if exp_writer is not None:
    exp_writer.write_step(sim_time, run_id, machine_metrics,
                          machine_health, spc_monitors, buffers)
```

At segment end, close writers:
```python
if exp_writer is not None:
    exp_writer.close()
if gt_writer is not None:
    gt_writer.close()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_fault_injector.py -v
pytest tests/ -q --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/experiment_writer.py src/opcua_server.py tests/test_fault_injector.py
git commit -m "feat: add ExperimentWriter thick CSV and --experiment-mode flag"
```

---

## Task 7: Experiment scenario in `line_models.yaml`

**Files:**
- Modify: `config/line_models.yaml`

The experiment scenario uses 4 machines with SPC, multi-state degradation, and RTF (run-to-failure) policy. `warm_up_time=1000` establishes the baseline. Injections start at sim_time=1500.

- [ ] **Step 1: Add scenario**

Append to `config/line_models.yaml`:

```yaml
anomaly_detection_experiment:
  # Scenario for Synthetic Anomaly Detectability experiment (MEng thesis).
  # Four machines, all SPC-enabled, RTF degradation policy.
  # warm_up_time=1000 establishes the SPC baseline before any injections.
  # Three fault injections demonstrate distinct anomaly signatures:
  #   M1 health_delta=2 at t=1500  → DEGRADED state + increased failure rate
  #                                   side effect: B1 starvation on M2
  #   M3 noise_ramp at t=2500      → gradual CPK degradation (tool wear)
  #   M4 cycle_time_offset at t=3500 → sudden SPC mean shift (setpoint change)
  warm_up_time: 1000
  historian:
    csv:
      enabled: true
    influxdb:
      enabled: false
  machines:
    - name: M1
      cycle_time: 1.0
      enable_degradation: true
      health_states: { h_max: 4, p_degrade: 0.003, cbm_threshold: 4 }
      enable_spc: true
      spc: { subgroup_size: 5, num_subgroups: 25, measurement_noise: 0.02 }
    - name: M2
      cycle_time: 1.1
      enable_degradation: true
      health_states: { h_max: 3, p_degrade: 0.003, cbm_threshold: 3 }
      enable_spc: true
      spc: { subgroup_size: 5, num_subgroups: 25, measurement_noise: 0.02 }
    - name: M3
      cycle_time: 1.0
      enable_degradation: true
      health_states: { h_max: 3, p_degrade: 0.002, cbm_threshold: 3 }
      enable_spc: true
      spc: { subgroup_size: 5, num_subgroups: 25, measurement_noise: 0.02 }
    - name: M4
      cycle_time: 1.2
      enable_degradation: true
      health_states: { h_max: 4, p_degrade: 0.003, cbm_threshold: 4 }
      enable_spc: true
      spc: { subgroup_size: 5, num_subgroups: 25, measurement_noise: 0.02 }
  buffers:
    - { name: B1, capacity: 10, upstream: M1, downstream: M2 }
    - { name: B2, capacity: 10, upstream: M2, downstream: M3 }
    - { name: B3, capacity: 10, upstream: M3, downstream: M4 }
  fault_injection:
    spc_noise_scale: 2.0
    injections:
      - type: health_delta
        machine: M1
        at_sim_time: 1500
        health_delta: 2
      - type: noise_ramp
        machine: M3
        at_sim_time: 2500
        duration: 200
        target_multiplier: 3.0
      - type: cycle_time_offset
        machine: M4
        at_sim_time: 3500
        offset: 0.25
```

- [ ] **Step 2: Verify scenario loads**

```bash
cd C:/PaulProjects/simantha-opcua
python -c "
import sys; sys.path.insert(0,'src'); sys.path.insert(0,'tests')
from config_loader import load_line_config
cfg = load_line_config('anomaly_detection_experiment')
print('machines:', [m['name'] for m in cfg['machines']])
fi = cfg['fault_injection']
print('injections:', len(fi['injections']))
print('spc_noise_scale:', fi['spc_noise_scale'])
"
```
Expected:
```
[OK] Configuration validated: 4 machines, 3 buffers
machines: ['M1', 'M2', 'M3', 'M4']
injections: 3
spc_noise_scale: 2.0
```

- [ ] **Step 3: Commit**

```bash
git add config/line_models.yaml
git commit -m "feat: add anomaly_detection_experiment scenario"
```

---

## Task 8: `experiment/generate_experiment_data.py`

**Files:**
- Create: `experiment/generate_experiment_data.py`
- Create: `experiment/experiment_config.yaml`

This script launches the OPC UA server as a subprocess with `--experiment-mode`. OPC UA runs normally and Telegraf can scrape it. The thick CSV and ground truth are written by the server process itself.

- [ ] **Step 1: Create `experiment/experiment_config.yaml`**

```yaml
# Experiment configuration for Synthetic Anomaly Detectability
# Run: python experiment/generate_experiment_data.py --config experiment/experiment_config.yaml

scenario: anomaly_detection_experiment
seed: 42
sim_speed: 10.0            # 10× wall-clock (run 6000 sim-seconds in ~10 minutes)
max_sim_time: 6000         # 1000s warm-up + 5000s production
output_dir: experiment/results

# Detection algorithm parameters (used by detect_anomalies.py)
detection:
  baseline_end_sim_time: 1000    # use first 1000 steps to establish baseline stats
  rolling_window: 50             # steps for rolling Z-score window
  zscore_threshold: 3.0          # standard deviations for alert
  isolation_forest_contamination: 0.05
  min_alert_spacing: 20          # minimum steps between consecutive alerts (same machine)
```

- [ ] **Step 2: Create `experiment/generate_experiment_data.py`**

```python
#!/usr/bin/env python
"""
generate_experiment_data.py — Drive the OPC UA server in experiment mode.

Launches opcua_server.py as a subprocess with --experiment-mode enabled.
The server runs in real-time with OPC UA exposed (Telegraf can scrape normally).
On completion, raw_data.csv and ground_truth.csv appear in --output-dir.

Usage:
    python experiment/generate_experiment_data.py
    python experiment/generate_experiment_data.py --config experiment/experiment_config.yaml
    python experiment/generate_experiment_data.py --seed 99 --sim-speed 20
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).parent.parent
SERVER_SCRIPT = PROJECT_ROOT / "src" / "opcua_server.py"


def main():
    parser = argparse.ArgumentParser(description="Run anomaly detection experiment")
    parser.add_argument("--config", default="experiment/experiment_config.yaml",
                        help="Experiment config YAML")
    parser.add_argument("--seed", type=int, default=None,
                        help="Override random seed from config")
    parser.add_argument("--sim-speed", type=float, default=None,
                        help="Override sim speed from config")
    parser.add_argument("--output-dir", default=None,
                        help="Override output directory from config")
    args = parser.parse_args()

    # Load experiment config
    config_path = Path(args.config)
    if not config_path.exists():
        sys.exit(f"Config not found: {config_path}")
    with open(config_path) as f:
        exp = yaml.safe_load(f)

    scenario    = exp.get("scenario", "anomaly_detection_experiment")
    seed        = args.seed        or exp.get("seed", 42)
    sim_speed   = args.sim_speed   or exp.get("sim_speed", 10.0)
    output_dir  = args.output_dir  or exp.get("output_dir", "experiment/results")
    max_sim     = exp.get("max_sim_time", 6000)

    # Build server command
    cmd = [
        sys.executable, str(SERVER_SCRIPT),
        "--scenario",          scenario,
        "--seed",              str(seed),
        "--sim-speed",         str(sim_speed),
        "--experiment-mode",
        "--experiment-output", output_dir,
    ]

    print(f"[experiment] scenario={scenario} seed={seed} sim_speed={sim_speed}x")
    print(f"[experiment] max_sim_time={max_sim}s  output_dir={output_dir}")
    print(f"[experiment] OPC UA endpoint: opc.tcp://localhost:4840/simantha/")
    print(f"[experiment] starting server... (Ctrl+C to abort)")
    print()

    start = time.time()
    result = subprocess.run(cmd)
    elapsed = time.time() - start

    if result.returncode == 0:
        print(f"\n[experiment] complete in {elapsed:.0f}s wall-clock")
        raw = Path(output_dir)
        csvs = list(raw.glob(f"*{scenario}*_raw_data.csv"))
        gts  = list(raw.glob(f"*{scenario}*_ground_truth.csv"))
        if csvs:
            import csv as _csv
            with open(csvs[-1]) as f:
                nrows = sum(1 for _ in f) - 1
            print(f"[experiment] raw_data:     {csvs[-1].name}  ({nrows} rows)")
        if gts:
            with open(gts[-1]) as f:
                ninj = sum(1 for _ in f) - 1
            print(f"[experiment] ground_truth: {gts[-1].name}  ({ninj} injections)")
        print(f"\nNext step: python experiment/detect_anomalies.py --results-dir {output_dir}")
    else:
        sys.exit(f"[experiment] server exited with code {result.returncode}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify script is importable and help works**

```bash
cd C:/PaulProjects/simantha-opcua
python experiment/generate_experiment_data.py --help
```
Expected: argparse help text, no errors

- [ ] **Step 4: Commit**

```bash
git add experiment/generate_experiment_data.py experiment/experiment_config.yaml
git commit -m "feat: add generate_experiment_data.py and experiment_config.yaml"
```

---

## Task 9: `experiment/detect_anomalies.py`

**Files:**
- Create: `experiment/detect_anomalies.py`

Three detection methods, each writes a section of `detection_results.csv`.

- [ ] **Step 1: Create `experiment/detect_anomalies.py`**

```python
#!/usr/bin/env python
"""
detect_anomalies.py — Apply three anomaly detection methods to raw_data.csv.

Methods:
  1. SPC rules   — read SPC_CumulativeOOC increments from the thick CSV.
                   An increment is a direct flag from the existing Western
                   Electric rule engine.  This is the baseline: if this
                   cannot detect what was injected, something is wrong upstream.

  2. Rolling Z-score — compute rolling mean/std over a baseline window for
                       each machine's SPC_XBar and OEE_Availability.  Alert
                       when Z-score exceeds threshold.  No training required.

  3. Isolation Forest — unsupervised multivariate detector trained on the
                        baseline period.  Feature set per machine:
                        SPC_XBar, SPC_Cpk, OEE, Availability,
                        ProcessingTime fraction, HealthState.

Outputs:
  detection_results.csv — one row per alert:
    method, machine, detected_sim_time, feature

Usage:
    python experiment/detect_anomalies.py --results-dir experiment/results
    python experiment/detect_anomalies.py --raw-data path/to/raw_data.csv
                                          --config experiment/experiment_config.yaml
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import yaml


PROJECT_ROOT = Path(__file__).parent.parent


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def find_latest_csv(results_dir: str, suffix: str) -> Path:
    paths = sorted(Path(results_dir).glob(f"*{suffix}"))
    if not paths:
        sys.exit(f"No {suffix} found in {results_dir}")
    return paths[-1]


# ---------------------------------------------------------------------------
# Method 1: SPC rules (CumulativeOOC increments)
# ---------------------------------------------------------------------------

def detect_spc_rules(df: pd.DataFrame, machines: list,
                     min_spacing: int = 20) -> list:
    """
    Flag each step where SPC_CumulativeOOC increments for any machine.
    Multiple consecutive alerts on the same machine are deduplicated using
    min_spacing (avoids counting a single event cluster as many detections).
    """
    alerts = []
    for m in machines:
        col = f"{m}_SPC_CumulativeOOC"
        if col not in df.columns:
            continue
        prev_ooc = df[col].shift(1, fill_value=0)
        triggered = df[col] > prev_ooc
        last_alert = -min_spacing
        for idx, row in df[triggered].iterrows():
            if row["sim_time"] - last_alert >= min_spacing:
                alerts.append({
                    "method": "spc_rules",
                    "machine": m,
                    "detected_sim_time": row["sim_time"],
                    "feature": col,
                })
                last_alert = row["sim_time"]
    return alerts


# ---------------------------------------------------------------------------
# Method 2: Rolling Z-score
# ---------------------------------------------------------------------------

def detect_rolling_zscore(df: pd.DataFrame, machines: list,
                           baseline_end: float, window: int,
                           threshold: float, min_spacing: int = 20) -> list:
    """
    For each machine, compute rolling mean/std from the baseline period.
    Alert when Z-score of SPC_XBar or Availability exceeds threshold.
    """
    baseline = df[df["sim_time"] <= baseline_end]
    alerts = []
    features = ["SPC_XBar", "Availability"]

    for m in machines:
        for feat in features:
            col = f"{m}_{feat}"
            if col not in df.columns:
                continue
            # Baseline statistics
            b_mean = baseline[col].mean()
            b_std  = baseline[col].std()
            if b_std == 0 or np.isnan(b_std):
                continue
            # Rolling Z-score on post-baseline data
            post = df[df["sim_time"] > baseline_end].copy()
            post["z"] = (post[col] - b_mean) / b_std
            triggered = post[post["z"].abs() > threshold]
            last_alert = -min_spacing
            for _, row in triggered.iterrows():
                if row["sim_time"] - last_alert >= min_spacing:
                    alerts.append({
                        "method": "rolling_zscore",
                        "machine": m,
                        "detected_sim_time": row["sim_time"],
                        "feature": col,
                    })
                    last_alert = row["sim_time"]
    return alerts


# ---------------------------------------------------------------------------
# Method 3: Isolation Forest
# ---------------------------------------------------------------------------

def detect_isolation_forest(df: pd.DataFrame, machines: list,
                             baseline_end: float, contamination: float,
                             min_spacing: int = 20) -> list:
    """
    Train IsolationForest on the baseline period using per-machine features.
    Score all post-baseline rows and alert when prediction == -1 (anomaly).
    """
    from sklearn.ensemble import IsolationForest

    alerts = []
    feature_suffixes = ["SPC_XBar", "SPC_Cpk", "OEE", "Availability",
                        "ProcessingTime", "DownTime", "HealthState"]

    for m in machines:
        cols = [f"{m}_{s}" for s in feature_suffixes if f"{m}_{s}" in df.columns]
        if not cols:
            continue

        baseline = df[df["sim_time"] <= baseline_end][cols].dropna()
        if len(baseline) < 50:
            print(f"  [IF] skipping {m}: baseline too short ({len(baseline)} rows)")
            continue

        post = df[df["sim_time"] > baseline_end][["sim_time"] + cols].dropna()
        if post.empty:
            continue

        clf = IsolationForest(contamination=contamination, random_state=42)
        clf.fit(baseline)
        preds = clf.predict(post[cols])

        last_alert = -min_spacing
        for i, pred in enumerate(preds):
            if pred == -1:
                t = post.iloc[i]["sim_time"]
                if t - last_alert >= min_spacing:
                    alerts.append({
                        "method": "isolation_forest",
                        "machine": m,
                        "detected_sim_time": t,
                        "feature": "multivariate",
                    })
                    last_alert = t
    return alerts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Detect anomalies in experiment CSV")
    parser.add_argument("--results-dir", default="experiment/results",
                        help="Directory containing raw_data.csv")
    parser.add_argument("--raw-data", default=None,
                        help="Explicit path to raw_data.csv (overrides --results-dir)")
    parser.add_argument("--config", default="experiment/experiment_config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    det = cfg.get("detection", {})
    baseline_end = det.get("baseline_end_sim_time", 1000)
    window       = det.get("rolling_window", 50)
    z_thresh     = det.get("zscore_threshold", 3.0)
    if_contam    = det.get("isolation_forest_contamination", 0.05)
    min_spacing  = det.get("min_alert_spacing", 20)

    raw_path = args.raw_data or find_latest_csv(args.results_dir, "_raw_data.csv")
    print(f"[detect] reading {raw_path}")
    df = pd.read_csv(raw_path)
    print(f"[detect] {len(df)} rows, sim_time {df['sim_time'].min():.0f}–{df['sim_time'].max():.0f}")

    # Infer machine names from column names
    machines = sorted({c.split("_")[0] for c in df.columns
                       if c.startswith("M") and "_State" in c})
    print(f"[detect] machines: {machines}")

    all_alerts = []

    print("[detect] method 1: SPC rules...")
    alerts1 = detect_spc_rules(df, machines, min_spacing)
    print(f"  → {len(alerts1)} alerts")
    all_alerts.extend(alerts1)

    print("[detect] method 2: rolling Z-score...")
    alerts2 = detect_rolling_zscore(df, machines, baseline_end, window,
                                    z_thresh, min_spacing)
    print(f"  → {len(alerts2)} alerts")
    all_alerts.extend(alerts2)

    print("[detect] method 3: Isolation Forest...")
    alerts3 = detect_isolation_forest(df, machines, baseline_end,
                                      if_contam, min_spacing)
    print(f"  → {len(alerts3)} alerts")
    all_alerts.extend(alerts3)

    # Write results
    out_path = str(raw_path).replace("_raw_data.csv", "_detection_results.csv")
    pd.DataFrame(all_alerts).to_csv(out_path, index=False)
    print(f"\n[detect] written → {out_path}")
    print(f"[detect] total alerts: {len(all_alerts)}")
    print(f"\nNext: python experiment/evaluate_results.py --results-dir {args.results_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify script imports and help**

```bash
cd C:/PaulProjects/simantha-opcua
python experiment/detect_anomalies.py --help
```
Expected: argparse help, no ImportError

- [ ] **Step 3: Commit**

```bash
git add experiment/detect_anomalies.py
git commit -m "feat: add three-method anomaly detection script"
```

---

## Task 10: `experiment/evaluate_results.py`

**Files:**
- Create: `experiment/evaluate_results.py`

- [ ] **Step 1: Create `experiment/evaluate_results.py`**

```python
#!/usr/bin/env python
"""
evaluate_results.py — Compare detection results against ground truth.

Loads ground_truth.csv (injection windows) and detection_results.csv
(algorithm outputs) for the same run_id.  Computes per-injection and
per-method evaluation metrics.

Evaluation definitions:
  True Positive (TP):    alert fires within [anomaly_window_start, anomaly_window_end]
                         for the correct machine
  False Positive (FP):   alert fires outside all anomaly windows for that machine
  False Negative (FN):   injection window with no alert from a given method
  Detection lag (s):     first_alert_sim_time − anomaly_window_start
  Warning lead time (s): anomaly_window_end − first_alert_sim_time
                         (positive = alert before failure; negative = alert after)

Outputs:
  evaluation_report.csv  — per-injection × per-method results
  evaluation_summary.csv — aggregated precision, recall, F1, mean lead time
  Printed summary table

Usage:
    python experiment/evaluate_results.py --results-dir experiment/results
"""
import argparse
import sys
from pathlib import Path

import pandas as pd


def find_latest_csv(results_dir: str, suffix: str) -> Path:
    paths = sorted(Path(results_dir).glob(f"*{suffix}"))
    if not paths:
        sys.exit(f"No {suffix} found in {results_dir}")
    return paths[-1]


def evaluate(gt: pd.DataFrame, det: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a DataFrame with one row per (injection_index, method) pair.
    """
    methods = det["method"].unique().tolist()
    rows = []

    for _, inj in gt.iterrows():
        machine   = inj["machine"]
        win_start = float(inj["anomaly_window_start"]) if inj["anomaly_window_start"] else None
        win_end   = float(inj["anomaly_window_end"])   if inj["anomaly_window_end"]   else None

        for method in methods:
            method_det = det[
                (det["method"]  == method) &
                (det["machine"] == machine)
            ].sort_values("detected_sim_time")

            row = {
                "injection_type":     inj["type"],
                "machine":            machine,
                "injection_sim_time": inj["injection_sim_time"],
                "anomaly_window_start": win_start,
                "anomaly_window_end":   win_end,
                "method":             method,
                "result":             "FN",
                "first_alert_sim_time": None,
                "detection_lag_s":    None,
                "warning_lead_time_s": None,
            }

            if win_start is None or win_end is None:
                row["result"] = "no_window"
                rows.append(row)
                continue

            # Find first alert within the window for this machine
            in_window = method_det[
                (method_det["detected_sim_time"] >= win_start) &
                (method_det["detected_sim_time"] <= win_end)
            ]
            if not in_window.empty:
                first_t = in_window.iloc[0]["detected_sim_time"]
                row["result"]               = "TP"
                row["first_alert_sim_time"] = first_t
                row["detection_lag_s"]      = first_t - float(inj["injection_sim_time"])
                row["warning_lead_time_s"]  = win_end - first_t
            rows.append(row)

    # Count FPs: alerts outside all windows for this machine
    fp_rows = []
    for method in methods:
        method_det = det[det["method"] == method]
        for _, alert in method_det.iterrows():
            m = alert["machine"]
            t = alert["detected_sim_time"]
            # Is this alert inside any window for this machine?
            machine_gt = gt[gt["machine"] == m]
            in_any = False
            for _, inj in machine_gt.iterrows():
                ws = float(inj["anomaly_window_start"]) if inj["anomaly_window_start"] else None
                we = float(inj["anomaly_window_end"])   if inj["anomaly_window_end"]   else None
                if ws is not None and we is not None and ws <= t <= we:
                    in_any = True
                    break
            if not in_any:
                fp_rows.append({
                    "injection_type": "N/A", "machine": m,
                    "injection_sim_time": None,
                    "anomaly_window_start": None, "anomaly_window_end": None,
                    "method": method, "result": "FP",
                    "first_alert_sim_time": t,
                    "detection_lag_s": None, "warning_lead_time_s": None,
                })

    return pd.DataFrame(rows + fp_rows)


def summarise(report: pd.DataFrame) -> pd.DataFrame:
    summary_rows = []
    for method in report["method"].unique():
        m_df = report[report["method"] == method]
        tp   = (m_df["result"] == "TP").sum()
        fn   = (m_df["result"] == "FN").sum()
        fp   = (m_df["result"] == "FP").sum()
        precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
        recall    = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) > 0 else float("nan"))
        lead_times = m_df[m_df["result"] == "TP"]["warning_lead_time_s"].dropna()
        summary_rows.append({
            "method":           method,
            "TP": tp, "FN": fn, "FP": fp,
            "precision":        round(precision, 3),
            "recall":           round(recall, 3),
            "f1":               round(f1, 3),
            "mean_lead_time_s": round(lead_times.mean(), 1) if not lead_times.empty else None,
            "min_lead_time_s":  round(lead_times.min(), 1)  if not lead_times.empty else None,
        })
    return pd.DataFrame(summary_rows)


def main():
    parser = argparse.ArgumentParser(description="Evaluate anomaly detection results")
    parser.add_argument("--results-dir", default="experiment/results")
    parser.add_argument("--ground-truth", default=None)
    parser.add_argument("--detections",   default=None)
    args = parser.parse_args()

    gt_path  = args.ground_truth  or find_latest_csv(args.results_dir, "_ground_truth.csv")
    det_path = args.detections    or find_latest_csv(args.results_dir, "_detection_results.csv")

    print(f"[eval] ground_truth:      {gt_path}")
    print(f"[eval] detection_results: {det_path}")

    gt  = pd.read_csv(gt_path)
    det = pd.read_csv(det_path)

    print(f"[eval] {len(gt)} injections, {len(det)} alerts")

    report  = evaluate(gt, det)
    summary = summarise(report)

    base = str(gt_path).replace("_ground_truth.csv", "")
    report.to_csv(f"{base}_evaluation_report.csv",  index=False)
    summary.to_csv(f"{base}_evaluation_summary.csv", index=False)

    print(f"\n[eval] written → {base}_evaluation_report.csv")
    print(f"[eval] written → {base}_evaluation_summary.csv")
    print()
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify imports**

```bash
python experiment/evaluate_results.py --help
```
Expected: argparse help, no errors

- [ ] **Step 3: Commit**

```bash
git add experiment/evaluate_results.py
git commit -m "feat: add evaluate_results.py with TP/FN/FP and lead-time metrics"
```

---

## Task 11: `experiment/README.md`

**Files:**
- Create: `experiment/README.md`

- [ ] **Step 1: Create README**

```markdown
# Anomaly Detection Experiment

End-to-end synthetic anomaly detectability study for the MEng thesis.
Demonstrates that the DES data generator produces datasets where injected
degradation events are statistically recoverable by standard methods.

## Quick Start

```bash
# 1. Generate data (runs OPC UA server at 10× speed, ~10 min wall-clock)
python experiment/generate_experiment_data.py

# 2. Detect anomalies (three methods, ~30 seconds)
python experiment/detect_anomalies.py

# 3. Evaluate against ground truth
python experiment/evaluate_results.py
```

Output files land in `experiment/results/`.

## What runs under the hood

`generate_experiment_data.py` launches `src/opcua_server.py` with
`--experiment-mode`, which:

- Publishes all KPIs over OPC UA in real time (Telegraf can scrape normally)
- Writes `{run_id}_raw_data.csv` — one row per simulation second, all KPIs
- Writes `{run_id}_ground_truth.csv` — injection events and failure timestamps

The DES is seeded (default `--seed 42`) so results are fully reproducible.

## Anomaly types injected

| Type | Machine | sim_time | Description |
|------|---------|----------|-------------|
| `health_delta` | M1 | 1500 | Health jumps 2 states → DEGRADED, accelerated failure |
| `noise_ramp` | M3 | 2500 | SPC measurement noise ramps to 3× over 200 steps (tool wear) |
| `cycle_time_offset` | M4 | 3500 | SPC nominal cycle time shifts +0.25s (setpoint change) |

Side effect: M1 degradation starves B1, creating a buffer starvation pattern on M2.

## Detection methods

| Method | Input features | Training required |
|--------|---------------|-----------------|
| SPC rules | `SPC_CumulativeOOC` increments | No |
| Rolling Z-score | `SPC_XBar`, `OEE_Availability` | No (baseline period only) |
| Isolation Forest | 6-feature multivariate per machine | Unsupervised (baseline) |

## Evaluation metrics

- **Detection rate** — fraction of injection windows with at least one TP
- **Warning lead time** — `anomaly_window_end − first_alert_sim_time` (seconds)
  Positive = alert before failure. Negative = alert after failure.
- **False positive rate** — alerts outside all injection windows

## Configuration

Edit `experiment/experiment_config.yaml` to adjust seed, sim speed, detection
thresholds, or anomaly timing. The scenario itself is defined in
`config/line_models.yaml` under key `anomaly_detection_experiment`.
```

- [ ] **Step 2: Commit**

```bash
git add experiment/README.md
git commit -m "docs: add experiment README quick-start guide"
```

---

## Task 12: Comprehensive experiment documentation

**Files:**
- Modify: `docs/experiments/anomaly_detection_experiment.md` (stub created in Task 1)

- [ ] **Step 1: Write comprehensive documentation**

Replace the stub with the full document. Sections required:

```markdown
# Anomaly Detection Experiment

## 1. Purpose and Thesis Argument
[Why this experiment exists; what claim it supports]

## 2. Signal Path
[DES → OPC UA (real-time) → Telegraf → InfluxDB (unchanged)
 └→ thick CSV (experiment mode only) → detection scripts]

## 3. Anomaly Type Design Rationale
### 3.1 health_delta — Degraded State + Accelerated Failure
[What it models, which OPC UA vars are affected, expected detection path]
### 3.2 noise_ramp — Gradual CPK Degradation (Tool Wear)
[noise_cv formula, expected XBar drift rate, Western Electric rules likely to fire]
### 3.3 cycle_time_offset — Sudden SPC Mean Shift (Setpoint Change)
[Effect on X-bar chart, Cpk change, detection lag expectation]
### 3.4 Buffer Starvation (Side Effect)
[Emerges from M1 health_delta; no separate injection needed; causal propagation demo]

## 4. Ground Truth Label Design
[CSV columns; anomaly_window_start/end definition per type; how failure_sim_time is filled;
 why natural stochastic failures are also captured]

## 5. noise_scale_per_health Parameter
[Formula: noise_cv_eff = noise_cv × (1 + scale × health/h_max);
 why scenario-level not per-machine; effect on Cpk at each health state;
 how to calibrate: at scale=2.0, h=h_max → CV triples → ~3σ WE Rule 2 violations expected
 within ~30–50 subgroups of injection]

## 6. Detection Methods
### 6.1 SPC Rules Baseline
### 6.2 Rolling Z-Score
### 6.3 Isolation Forest
[Feature set rationale; why unsupervised; contamination parameter choice]

## 7. Evaluation Framework
[TP/FN/FP definitions; detection lag; warning lead time; MTTR benchmark;
 why partial detection with documented FPs is still a valid thesis result]

## 8. Reproducing the Experiment
[Full command sequence; expected runtime; expected output files;
 how to vary noise_scale or injection timing]

## 9. Interpreting Results
[What "good enough" looks like for the thesis claim;
 what failure modes mean and what to write about them;
 connection to real-world maintenance scheduling value]
```

Full prose content for each section should be written drawing on the design
decisions documented throughout the conversation that produced this plan.
The document should stand alone: a reader unfamiliar with the codebase should
understand what was done, why, and what the results mean.

- [ ] **Step 2: Commit**

```bash
git add docs/experiments/anomaly_detection_experiment.md
git commit -m "docs: write comprehensive anomaly detection experiment documentation"
```

---

## Task 13: End-to-end smoke test

- [ ] **Step 1: Run a short smoke test to verify the full pipeline**

```bash
cd C:/PaulProjects/simantha-opcua
python src/opcua_server.py \
  --scenario anomaly_detection_experiment \
  --seed 42 \
  --sim-speed 100 \
  --experiment-mode \
  --experiment-output experiment/results \
  --no-csv &

# Let it run for 60 seconds of wall-clock (= 6000 sim-seconds at 100×)
sleep 65
kill %1
```

- [ ] **Step 2: Verify output files exist and have content**

```bash
ls -la experiment/results/
python -c "
import pandas as pd
import glob
raw = sorted(glob.glob('experiment/results/*_raw_data.csv'))[-1]
gt  = sorted(glob.glob('experiment/results/*_ground_truth.csv'))[-1]
df = pd.read_csv(raw)
gt_df = pd.read_csv(gt)
print(f'raw_data: {len(df)} rows, {len(df.columns)} columns')
print(f'ground_truth: {len(gt_df)} rows')
print('max sim_time:', df.sim_time.max())
print('injections fired:', gt_df.type.tolist())
"
```

Expected: ~6000 rows in raw_data.csv, 3 rows in ground_truth.csv (one per injection).

- [ ] **Step 3: Run detection and evaluation on the smoke test output**

```bash
python experiment/detect_anomalies.py --results-dir experiment/results
python experiment/evaluate_results.py --results-dir experiment/results
```

Expected: no crashes, evaluation_summary.csv written, summary table printed.

- [ ] **Step 4: Run full regression test suite**

```bash
pytest tests/ -q --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py
```
Expected: all pass

- [ ] **Step 5: Final commit**

```bash
git add experiment/ docs/experiments/ requirements.txt
git commit -m "feat: complete anomaly detection experiment — inject, record, detect, evaluate"
git push origin main
```
