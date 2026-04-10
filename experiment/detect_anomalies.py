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
    print(f"  -> {len(alerts1)} alerts")
    all_alerts.extend(alerts1)

    print("[detect] method 2: rolling Z-score...")
    alerts2 = detect_rolling_zscore(df, machines, baseline_end, window,
                                    z_thresh, min_spacing)
    print(f"  -> {len(alerts2)} alerts")
    all_alerts.extend(alerts2)

    print("[detect] method 3: Isolation Forest...")
    alerts3 = detect_isolation_forest(df, machines, baseline_end,
                                      if_contam, min_spacing)
    print(f"  -> {len(alerts3)} alerts")
    all_alerts.extend(alerts3)

    # Write results (always write header even if no alerts)
    out_path = str(raw_path).replace("_raw_data.csv", "_detection_results.csv")
    cols = ["method", "machine", "detected_sim_time", "feature"]
    pd.DataFrame(all_alerts, columns=cols).to_csv(out_path, index=False)
    print(f"\n[detect] written -> {out_path}")
    print(f"[detect] total alerts: {len(all_alerts)}")
    print(f"\nNext: python experiment/evaluate_results.py --results-dir {args.results_dir}")


if __name__ == "__main__":
    main()
