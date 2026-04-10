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
