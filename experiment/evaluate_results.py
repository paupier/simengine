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
        # pd.read_csv converts empty CSV cells to NaN (float), which is truthy
        # in Python.  Explicitly check with pd.notna() to avoid treating NaN
        # as a valid window bound.
        win_start = float(inj["anomaly_window_start"]) if pd.notna(inj["anomaly_window_start"]) and inj["anomaly_window_start"] != "" else None
        win_end   = float(inj["anomaly_window_end"])   if pd.notna(inj["anomaly_window_end"])   and inj["anomaly_window_end"]   != "" else None

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

            if win_start is None:
                row["result"] = "no_window"
                rows.append(row)
                continue

            # Find first alert within the window for this machine.
            # win_end=None means the window is open-ended (extends to end of run).
            if win_end is not None:
                in_window = method_det[
                    (method_det["detected_sim_time"] >= win_start) &
                    (method_det["detected_sim_time"] <= win_end)
                ]
            else:
                in_window = method_det[method_det["detected_sim_time"] >= win_start]

            if not in_window.empty:
                first_t = in_window.iloc[0]["detected_sim_time"]
                row["result"]               = "TP"
                row["first_alert_sim_time"] = first_t
                row["detection_lag_s"]      = first_t - float(inj["injection_sim_time"])
                row["warning_lead_time_s"]  = (win_end - first_t) if win_end is not None else None
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
                ws = float(inj["anomaly_window_start"]) if pd.notna(inj["anomaly_window_start"]) and inj["anomaly_window_start"] != "" else None
                we = float(inj["anomaly_window_end"])   if pd.notna(inj["anomaly_window_end"])   and inj["anomaly_window_end"]   != "" else None
                # Open-ended window (we=None): any alert after ws counts as inside window
                if ws is not None and (we is None and t >= ws or we is not None and ws <= t <= we):
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

    result_cols = [
        "injection_type", "machine", "injection_sim_time",
        "anomaly_window_start", "anomaly_window_end", "method", "result",
        "first_alert_sim_time", "detection_lag_s", "warning_lead_time_s",
    ]
    return pd.DataFrame(rows + fp_rows, columns=result_cols if not (rows + fp_rows) else None)


def summarise(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty or "method" not in report.columns:
        return pd.DataFrame(columns=["method", "TP", "FN", "FP",
                                     "precision", "recall", "f1",
                                     "mean_lead_time_s", "min_lead_time_s"])
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
    try:
        det = pd.read_csv(det_path)
    except Exception:
        det = pd.DataFrame(columns=["method", "machine", "detected_sim_time", "feature"])

    print(f"[eval] {len(gt)} injections, {len(det)} alerts")

    report  = evaluate(gt, det)
    summary = summarise(report)

    base = str(gt_path).replace("_ground_truth.csv", "")
    report.to_csv(f"{base}_evaluation_report.csv",  index=False)
    summary.to_csv(f"{base}_evaluation_summary.csv", index=False)

    print(f"\n[eval] written -> {base}_evaluation_report.csv")
    print(f"[eval] written -> {base}_evaluation_summary.csv")
    print()
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
