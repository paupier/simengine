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

    scenario   = exp.get("scenario", "anomaly_detection_experiment")
    seed       = args.seed       or exp.get("seed", 42)
    sim_speed  = args.sim_speed  or exp.get("sim_speed", 10.0)
    output_dir = args.output_dir or exp.get("output_dir", "experiment/results")
    max_sim    = exp.get("max_sim_time", 6000)

    # Build server command
    cmd = [
        sys.executable, str(SERVER_SCRIPT),
        "--scenario",          scenario,
        "--seed",              str(seed),
        "--sim-speed",         str(sim_speed),
        "--max-sim-time",      str(max_sim),
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
