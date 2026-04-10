# Anomaly Detection Experiment

## 1. Purpose and Thesis Argument

This experiment tests whether the Simantha-OPC UA discrete-event simulation (DES) platform produces datasets in which deliberately injected degradation events are statistically recoverable by standard anomaly detection methods. The thesis claim is:

> *A synthetic digital-twin DES can serve as a controlled ground-truth generator for anomaly detection research, enabling method comparison without requiring physical failure data.*

The experiment provides evidence for this claim by:
1. Injecting three distinct fault types into a running simulation
2. Recording the full OPC UA KPI stream as a thick CSV alongside the live OPC UA publish path
3. Running three detection methods of increasing sophistication
4. Comparing detection output against an automatically-generated ground truth

A positive result (all three injections detected with positive warning lead time) confirms the DES generates statistically distinct anomaly signatures. A partial result (some missed, some false positives) is also a valid thesis finding — it characterises method sensitivity and is more realistic than a toy result.

---

## 2. Signal Path

```
Simantha DES (1Hz, seeded)
  │
  ├── OPC UA server (real-time, unchanged)
  │     └── Telegraf → InfluxDB → Grafana  (monitoring, unchanged)
  │
  └── [--experiment-mode only]
        ├── {run_id}_raw_data.csv    (one row per simulation second, all KPIs)
        └── {run_id}_ground_truth.csv (injection events + failure timestamps)

Detection scripts consume raw_data.csv:
  detect_anomalies.py   → {run_id}_detection_results.csv
  evaluate_results.py   → {run_id}_evaluation_report.csv
                        → {run_id}_evaluation_summary.csv
```

The OPC UA path is not modified. The thick CSV records the same values just published to OPC UA, written as a flat file per step. Nothing is removed from the existing runtime path.

---

## 3. Anomaly Type Design Rationale

Three injection types cover the space of anomaly signatures seen in real manufacturing:

### 3.1 `health_delta` — Degraded State + Accelerated Failure

**Injected:** M1 at sim_time=1500, `health_delta=2`

**What it models:** A sudden jump in the Markov health state — equivalent to an undetected impact event (dropped tool, hard feed) that accelerates wear. The machine continues operating (not failed) but is closer to the failure threshold.

**Observable effects:**
- `M1_State` transitions from IDLE/PROCESSING to `DEGRADED` on the injection step
- `M1_HealthState` jumps from its current value by +2 (clamped to h_max=4)
- With `spc_noise_scale=2.0`, the SPC measurement noise on M1 immediately increases proportionally to the new health state (formula below)
- Accelerated natural degradation increases the frequency of `FAILED`/`UNDER_REPAIR` events
- **Side effect:** when M1 is FAILED, B1 drains → M2 starves → `M2_StarvedTime` rises, `M2_Availability` drops. This causal propagation emerges from the line dynamics, no separate injection needed.

**Expected detection path:** SPC CumulativeOOC increment (noise increase), rolling Z-score on `M1_SPC_XBar` or `M1_Availability`.

### 3.2 `noise_ramp` — Gradual CPK Degradation (Tool Wear)

**Injected:** M3 at sim_time=2500, `duration=200`, `target_multiplier=3.0`

**What it models:** Progressive tool wear. The SPC measurement noise coefficient of variation (CV) linearly increases from its baseline value to 3× baseline over 200 simulation steps, then holds at 3×.

**Noise formula during ramp:**
```
noise_cv_eff = initial_noise_cv × (1 + progress × (target_multiplier − 1))
```
At `progress=0.5` (step 100): CV = 1.02×initial. At `progress=1.0` (step 200): CV = 3×initial.

**Observable effects:**
- `M3_SPC_XBar` variance grows gradually; control chart range (R) widens
- `M3_SPC_Cpk` degrades as process spread increases relative to spec limits
- Western Electric Rule 2 (9 points same side) and Rule 3 (6 points trending) are likely to fire as variance grows
- `M3_SPC_CumulativeOOC` increments when WE rules trigger

**Expected detection path:** SPC rules (most sensitive for gradual CV increase), Isolation Forest (multivariate variance change).

### 3.3 `cycle_time_offset` — Sudden SPC Mean Shift (Setpoint Change)

**Injected:** M4 at sim_time=3500, `offset=+0.25s`

**What it models:** A machine setpoint change (feed rate adjustment, tooling swap) that shifts the process mean without changing the actual simulation cycle time. In practice this represents the nominal target shifting while the machine continues producing at the same physical rate.

**Implementation:** Sets `metrics["spc_target_cycle_time"] = original_cycle_time + offset`. The SPC measurement generator uses `spc_target_cycle_time` as the nominal mean (instead of `cycle_time`) when `cycle_time_offset` is active. The actual `machine_obj.cycle_time` is **not** changed (per the CLAUDE.md constraint).

**Observable effects:**
- `M4_SPC_XBar` shifts by +0.25s above the control chart's established centreline
- Immediate Western Electric Rule 1 violation (point outside 3σ bounds) if offset > 3×noise_cv×cycle_time
- `M4_SPC_Cpk` drops (process mean has moved away from centre of spec window)
- `M4_SPC_CumulativeOOC` increments on the shift step

**Expected detection path:** SPC Rule 1 (most direct), rolling Z-score on `M4_SPC_XBar`.

### 3.4 Buffer Starvation (Side Effect of 3.1)

The M1 health_delta injection (3.1) causes increased FAILED/UNDER_REPAIR events. Each failure episode drains B1 while M1 is offline, starving M2. This is an emergent causal propagation through the line topology — no injection is needed. It demonstrates that the digital twin propagates fault effects realistically through the production network.

---

## 4. Ground Truth Label Design

The ground truth CSV (`{run_id}_ground_truth.csv`) is written as a side effect of injection firing, not reconstructed post-hoc. Each row represents one injection event.

**Columns:**

| Column | Description |
|--------|-------------|
| `run_id` | Simulation run identifier |
| `type` | Injection type: `health_delta`, `noise_ramp`, `cycle_time_offset` |
| `machine` | Target machine name |
| `injection_sim_time` | Simulation time when injection fired |
| `health_before` / `health_after` | Health state delta (health_delta only) |
| `h_max` | Maximum health state for this machine |
| `initial_noise` / `target_multiplier` / `duration` | Noise ramp parameters |
| `original_cycle_time` / `offset` | Cycle time offset parameters |
| `failure_sim_time` | When the machine first reached failed_health after injection (health_delta only) |
| `repair_complete_sim_time` | When repair completed (health_delta only) |
| `anomaly_window_start` | Start of the anomaly window (= injection_sim_time) |
| `anomaly_window_end` | End of the anomaly window (see below) |

**Anomaly window definitions:**
- `health_delta`: `[injection_sim_time, repair_complete_sim_time]` — window closes when machine recovers. If no failure occurs before run end, `anomaly_window_end` is blank (detection within any degraded period counts as TP).
- `noise_ramp`: `[injection_sim_time, injection_sim_time + duration]` — window spans the active ramp.
- `cycle_time_offset`: `[injection_sim_time, ∞]` — window never closes (permanent shift). Left blank in CSV; evaluator treats any post-injection alert as TP.

Natural stochastic failures (occurring independently of injections) are also captured via `notify_failure()` / `notify_repair_complete()` in the repair countdown loop. This means the ground truth captures both injected-accelerated and coincidental natural failures on the target machine.

---

## 5. `noise_scale_per_health` Parameter

The `spc_noise_scale` is a scenario-level parameter (not per-machine) that makes SPC measurement noise scale with the machine's current health state:

```
noise_cv_eff = noise_cv × (1 + spc_noise_scale × health_state / h_max)
```

**Why scenario-level:** All machines in the experiment use the same measurement setup, and the noise-health relationship is a property of the measurement process (sensor sensitivity to vibration), not an individual machine parameter. Keeping it scenario-level also makes it a single experimental variable — changing it affects all machines equally, enabling clean comparison.

**Effect at each health state (h_max=4, base_noise_cv=0.02, scale=2.0):**

| health_state | noise_cv_eff | Expected SPC spread |
|-------------|-------------|---------------------|
| 0 | 0.02 | Baseline |
| 1 | 0.03 | 1.5× wider |
| 2 | 0.04 | 2× wider |
| 3 | 0.05 | 2.5× wider |
| 4 (failed) | 0.06 | 3× wider |

**Calibration guidance:** At `scale=2.0` and `h_max=4`, a `health_delta=2` injection (from health=0 to health=2) doubles the noise CV. With a doubling of CV, Western Electric Rule 2 (9 of 10 consecutive points on same side of centre) is expected to trigger within ~30–50 subgroups of the injection, providing reliable detection without being instantaneous.

---

## 6. Detection Methods

Three methods of increasing complexity are applied to `raw_data.csv`. All methods consume the same file and produce rows in `detection_results.csv` with columns: `method`, `machine`, `detected_sim_time`, `feature`.

### 6.1 SPC Rules Baseline

**Method:** Read `{M}_SPC_CumulativeOOC` increments from the thick CSV. Each increment indicates a Western Electric rule violation fired on that machine at that step. Consecutive alerts on the same machine within `min_spacing` steps are deduplicated.

**Why this is the baseline:** The CumulativeOOC counter is computed by the same simulation that generates the injections. If this method fails to detect an injection, the SPC noise parameters are too low and need recalibration — the problem is upstream, not in the detector.

**Sensitivity:** Very high sensitivity to noise_ramp and cycle_time_offset (direct SPC signal). Moderate sensitivity to health_delta (only detects if noise_scale_per_health is non-zero and health change is significant).

### 6.2 Rolling Z-Score

**Method:** For each machine, compute the mean and standard deviation of `SPC_XBar` and `Availability` over the baseline period (`sim_time <= baseline_end_sim_time`). For each post-baseline step, compute the Z-score. Alert when |Z| exceeds `zscore_threshold` (default 3.0).

**Advantages:** No training required beyond the baseline period. Sensitive to both sustained shifts (cycle_time_offset) and variance increases (noise_ramp).

**Limitations:** Uses a fixed baseline mean — if the process drifts naturally during baseline, the mean is inflated. Availability is a cumulative metric that changes slowly; the Z-score may lag the injection by several hundred steps.

### 6.3 Isolation Forest

**Method:** Train `sklearn.ensemble.IsolationForest` on the baseline period using a 7-feature vector per machine: `SPC_XBar`, `SPC_Cpk`, `OEE`, `Availability`, `ProcessingTime`, `DownTime`, `HealthState`. Score all post-baseline rows. Alert when `predict() == -1` (anomaly).

**Why unsupervised:** There are no labelled anomaly examples to train on (that would defeat the purpose of the experiment). Isolation Forest is effective at detecting multivariate outliers in manufacturing data and requires only baseline "normal" data.

**Contamination parameter:** Set to 0.05 (5% of baseline data expected to be anomalous). This is a conservative estimate; if the baseline period (`warm_up_time=1000`) is clean, the actual contamination is near zero.

**Feature set rationale:** Includes both SPC signals (XBar, Cpk) and operational signals (OEE, Availability) to catch both the direct signal (SPC degradation) and the causal propagation (reduced Availability after failures). HealthState is included as a direct feature because health_delta injections are immediately visible in it.

---

## 7. Evaluation Framework

### Definitions

| Term | Definition |
|------|-----------|
| **True Positive (TP)** | At least one alert fires within `[anomaly_window_start, anomaly_window_end]` for the correct machine |
| **False Negative (FN)** | No alert fires within the anomaly window for a given injection × method pair |
| **False Positive (FP)** | Alert fires outside all anomaly windows for a machine |
| **Detection lag** | `first_alert_sim_time − injection_sim_time` (seconds). May be negative if alert precedes injection (e.g., coincidental SPC event). |
| **Warning lead time** | `anomaly_window_end − first_alert_sim_time`. Positive = alert before window end. For health_delta, window end is repair_complete, so positive lead time means the alert fired before the machine finished its repair. |

### MTTR benchmark

For `health_delta` injections, the warning lead time relative to MTTR is particularly meaningful. If the mean repair time is ~20–30 seconds and the warning lead time is positive, the detection method could theoretically trigger a maintenance scheduling action before repair starts — demonstrating actionable early warning.

### Interpreting partial detection

A thesis result showing partial detection (e.g., 2/3 injections detected, 1 missed) is interpretable as:
- **Method 1 misses noise_ramp:** SPC noise scale is too low for the WE rules to trigger within the ramp window. Recommendation: increase `spc_noise_scale` or extend `duration`.
- **Method 2 misses health_delta:** Availability metric changes too slowly for rolling Z-score. Expected: Isolation Forest (multivariate) catches it via `HealthState` feature.
- **Method 3 has high FP rate:** baseline period is not clean (natural degradation events during warm-up). Mitigation: extend `warm_up_time` or increase `min_alert_spacing`.

---

## 8. Reproducing the Experiment

### Prerequisites

```bash
pip install -r requirements.txt  # includes scikit-learn>=1.3.0
```

### Full command sequence

```bash
# 1. Generate data (10× speed = ~10 min wall-clock for 6000 sim-seconds)
python experiment/generate_experiment_data.py

# 2. Detect anomalies (~30 seconds)
python experiment/detect_anomalies.py --results-dir experiment/results

# 3. Evaluate
python experiment/evaluate_results.py --results-dir experiment/results
```

### Expected runtime

| Phase | Wall-clock |
|-------|-----------|
| Data generation (6000 sim-s at 10×) | ~10 minutes |
| Detection (3 methods) | ~30 seconds |
| Evaluation | <5 seconds |

### Expected output files

```
experiment/results/
  {run_id}_raw_data.csv          (~6000 rows × ~50 columns)
  {run_id}_ground_truth.csv      (3 injection rows)
  {run_id}_detection_results.csv (alerts from all 3 methods)
  {run_id}_evaluation_report.csv (per-injection × per-method)
  {run_id}_evaluation_summary.csv (precision/recall/F1 by method)
```

### Varying parameters

**Change noise sensitivity:**
```yaml
# config/line_models.yaml → anomaly_detection_experiment → fault_injection
fault_injection:
  spc_noise_scale: 3.0  # was 2.0; higher = faster WE rule triggers
```

**Change injection timing:**
```yaml
injections:
  - type: health_delta
    machine: M1
    at_sim_time: 2000   # was 1500; adjust to move outside baseline
```

**Change detection thresholds:**
```yaml
# experiment/experiment_config.yaml → detection
detection:
  zscore_threshold: 2.5   # was 3.0; lower = more sensitive, more FPs
```

---

## 9. Interpreting Results

### What "good enough" looks like for the thesis claim

The thesis claim is validated if:
1. All three injection types produce at least one TP across the three detection methods
2. At least one method achieves detection_lag < injection_duration (for noise_ramp)
3. False positive rate is bounded (< 20% of total alerts are FP)

This does not require all three methods to detect all three anomalies — the point is that the DES generates recoverable signals, not that any particular method is optimal.

### What failure modes mean

| Failure | Interpretation | Recommended action |
|---------|---------------|-------------------|
| All methods miss noise_ramp | SPC noise scale too low | Increase `spc_noise_scale` to 3.0+ |
| Method 2/3 miss health_delta | OEE/availability signal too slow | Add `HealthState` to Z-score features, or inspect `M1_SPC_XBar` directly |
| High FP on M2 | Causal propagation (B1 starvation) triggers detectors on the wrong machine | This is expected; downstream effects are correctly attributed to M1 via ground truth |
| cycle_time_offset detected immediately | SPC offset is large relative to noise | Expected; confirms the SPC measurement path is working |

### Connection to real-world value

The warning lead time metric is directly interpretable as maintenance scheduling value. A positive lead time of 100 seconds at 1× real-time means the algorithm would give 100 seconds of advance notice before a failure — sufficient to schedule a maintenance crew for the next available window rather than reacting to an unplanned stop.

For a thesis context, the key argument is not that any method is production-ready, but that the DES platform provides a principled, reproducible testbed for validating such claims before deploying to a physical asset.
