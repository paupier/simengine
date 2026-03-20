"""
Report Engine — importable analysis functions for historian CSV data.

Each section of the analysis returns a JSON-serializable dict suitable for
both CLI text formatting and Flask/Chart.js rendering.

Used by:
  - tools/analyze_historian.py (CLI text report)
  - docker/webui/app.py (Flask API for web reports)
"""
import json
import os
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None  # Deferred error when functions are called


def _require_pandas():
    if pd is None:
        raise ImportError("pandas is required. Install with: pip install pandas")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_latest_csv(directory):
    """Find the most recent historian CSV file in a directory.

    Returns the path string, or None if no CSV files found.
    """
    csvs = sorted(Path(directory).glob("*_events*.csv"), key=os.path.getmtime)
    if not csvs:
        return None
    return str(csvs[-1])


def _rotation_sort_key(p):
    """Sort rotation files: base file (_events.csv) first, then _events_001, _002, ..."""
    stem = Path(p).stem
    import re as _re
    m = _re.search(r"_events_(\d+)$", stem)
    return int(m.group(1)) if m else -1


def find_run_csv_files(path):
    """Return all rotation CSV files for the same run_id as *path*, sorted in order.

    Given any one file in a rotation set (e.g. events.csv or events_001.csv),
    finds all sibling files in the same directory that share the same run_id prefix.
    """
    path = Path(path)
    stem = path.stem  # e.g. "full_feature_8_machine_line_20260318_211446_events_001"
    run_id = stem.rsplit("_events", 1)[0] if "_events" in stem else stem
    files = sorted(path.parent.glob(f"{run_id}_events*.csv"), key=_rotation_sort_key)
    return files if files else [path]


def load_historian_csv(path):
    """Load historian CSV with appropriate dtypes.

    Handles both old CSVs (without run_id column) and new ones (with run_id).
    """
    _require_pandas()
    df = pd.read_csv(path, dtype={
        "run_id": str,
        "timestamp": float,
        "event_type": str,
        "source": str,
        "source_type": str,
        "severity": str,
        "message": str,
        "old_state": str,
        "new_state": str,
        "partcount": "Int64",
        "good_parts": "Int64",
        "defective_parts": "Int64",
        "buffer_level": "Int64",
        "oee": float,
        "utilisation": float,
        "shift_number": "Int64",
        "shift_name": str,
        "extra_json": str,
    })
    # Backward compatibility: old CSVs lack run_id column
    if "run_id" not in df.columns:
        df.insert(0, "run_id", "")
    return df


def load_merged_historian_csv(path):
    """Load and merge all rotation files for the same run_id as *path*.

    Returns a single concatenated DataFrame sorted by timestamp, covering the
    full run regardless of how many 50 MB rotation files were created.
    """
    _require_pandas()
    files = find_run_csv_files(path)
    dfs = [load_historian_csv(str(f)) for f in files]
    if len(dfs) == 1:
        return dfs[0]
    merged = pd.concat(dfs, ignore_index=True)
    merged.sort_values("timestamp", inplace=True, ignore_index=True)
    return merged


def parse_extra_json(series):
    """Parse extra_json column into dicts, handling NaN/empty."""
    def _parse(val):
        if pd.isna(val) or val == "":
            return {}
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return {}
    return series.apply(_parse)


def _downsample(timestamps, values, max_points=500):
    """Downsample parallel lists to at most max_points for chart rendering.

    Uses simple stride-based decimation preserving first and last points.
    Returns (list_of_timestamps, list_of_values).
    """
    n = len(timestamps)
    if n <= max_points:
        return list(timestamps), list(values)
    step = max(1, n // max_points)
    indices = list(range(0, n, step))
    if indices[-1] != n - 1:
        indices.append(n - 1)
    return [timestamps[i] for i in indices], [values[i] for i in indices]


def _to_timeseries(timestamps, values, max_points=500):
    """Convert parallel arrays to [{"t": float, "v": float}, ...] format,
    downsampled to max_points."""
    ts, vs = _downsample(list(timestamps), list(values), max_points)
    return [{"t": t, "v": v} for t, v in zip(ts, vs)]


def _safe_float(val):
    """Convert a value to float, returning None if not possible."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Section 1: Overview
# ---------------------------------------------------------------------------

def analyze_overview(df):
    """Section 1: event counts, time range, event type distribution."""
    _require_pandas()
    sim_start = float(df["timestamp"].min())
    sim_end = float(df["timestamp"].max())
    sim_duration_s = sim_end  # sim_time starts from 0
    sim_duration_hrs = sim_duration_s / 3600
    total_events = len(df)
    events_per_min = total_events / max(sim_duration_hrs * 60, 1)

    wall_start = str(df["wall_clock"].iloc[0]) if "wall_clock" in df.columns else None
    wall_end = str(df["wall_clock"].iloc[-1]) if "wall_clock" in df.columns else None
    wall_duration_hrs = None
    if wall_start and wall_end:
        try:
            dt_start = datetime.fromisoformat(wall_start)
            dt_end = datetime.fromisoformat(wall_end)
            wall_duration_hrs = round((dt_end - dt_start).total_seconds() / 3600, 2)
        except (ValueError, TypeError):
            pass

    # Event type distribution
    event_type_dist = {}
    for etype, count in df["event_type"].value_counts().items():
        event_type_dist[etype] = {
            "count": int(count),
            "pct": round(100 * count / total_events, 1),
        }

    # Severity distribution
    severity_dist = {}
    for sev, count in df["severity"].value_counts().items():
        severity_dist[sev] = int(count)

    return {
        "total_events": total_events,
        "sim_start": sim_start,
        "sim_end": sim_end,
        "sim_duration_s": sim_duration_s,
        "sim_duration_hrs": round(sim_duration_hrs, 1),
        "events_per_min": round(events_per_min, 1),
        "wall_start": wall_start,
        "wall_end": wall_end,
        "wall_duration_hrs": wall_duration_hrs,
        "event_type_distribution": event_type_dist,
        "severity_distribution": severity_dist,
    }


# ---------------------------------------------------------------------------
# Section 2: Continuity Check
# ---------------------------------------------------------------------------

def analyze_continuity(df):
    """Section 2: production summary interval regularity, gaps."""
    _require_pandas()
    prod_summaries = df[df["event_type"] == "PRODUCTION_SUMMARY"].copy()
    result = {
        "production_summary_count": len(prod_summaries),
        "status": "PASS",
    }

    if len(prod_summaries) > 1:
        gaps = prod_summaries["timestamp"].diff()
        expected_interval = float(gaps.median())
        large_gaps = gaps[gaps > expected_interval * 3].dropna()
        result["expected_interval_s"] = round(expected_interval, 0)
        result["large_gap_count"] = len(large_gaps)

        gap_details = []
        for idx in large_gaps.index[:5]:
            row = prod_summaries.loc[idx]
            gap_details.append({
                "timestamp": float(row["timestamp"]),
                "gap_s": float(gaps.loc[idx]),
            })
        result["large_gaps"] = gap_details

        if len(large_gaps) > 0:
            result["status"] = "WARN"
    else:
        result["status"] = "WARN"
        result["message"] = f"Too few production summaries ({len(prod_summaries)}) to check continuity"

    return result


# ---------------------------------------------------------------------------
# Section 3: Line OEE Analysis
# ---------------------------------------------------------------------------

def analyze_oee(df):
    """Section 3: line OEE stats + timeseries."""
    _require_pandas()
    prod_summaries = df[df["event_type"] == "PRODUCTION_SUMMARY"].copy()
    result = {
        "sample_count": 0,
        "status": "PASS",
        "timeseries": [],
    }

    if len(prod_summaries) == 0:
        result["status"] = "WARN"
        result["message"] = "No production summaries found"
        return result

    extras = parse_extra_json(prod_summaries["extra_json"])
    prod_summaries["line_oee"] = extras.apply(lambda x: x.get("line_oee", None))
    prod_summaries["line_oee"] = pd.to_numeric(prod_summaries["line_oee"], errors="coerce")
    valid_oee = prod_summaries["line_oee"].dropna()

    if len(valid_oee) == 0:
        result["status"] = "WARN"
        result["message"] = "No line_oee data found in extra_json"
        return result

    result["sample_count"] = len(valid_oee)
    result["mean"] = _safe_float(valid_oee.mean())
    result["median"] = _safe_float(valid_oee.median())
    result["std"] = _safe_float(valid_oee.std())
    result["min"] = _safe_float(valid_oee.min())
    result["min_timestamp"] = _safe_float(prod_summaries.loc[valid_oee.idxmin(), "timestamp"])
    result["max"] = _safe_float(valid_oee.max())
    result["max_timestamp"] = _safe_float(prod_summaries.loc[valid_oee.idxmax(), "timestamp"])

    # OEE stability check (bucket behavior)
    oee_changes = valid_oee.diff().abs().dropna()
    if len(oee_changes) > 0:
        unchanged = int((oee_changes < 0.0001).sum())
        changed = int((oee_changes >= 0.0001).sum())
        unchanged_pct = round(100 * unchanged / len(oee_changes), 1)
        result["unchanged_between_summaries"] = unchanged
        result["changed_between_summaries"] = changed
        result["unchanged_pct"] = unchanged_pct

        if unchanged / max(len(oee_changes), 1) > 0.8:
            result["stability_status"] = "PASS"
        elif unchanged / max(len(oee_changes), 1) > 0.5:
            result["stability_status"] = "WARN"
        else:
            result["stability_status"] = "FAIL"

    # OEE spikes to 1.0
    spikes = int((valid_oee >= 0.999).sum())
    spikes_pct = round(100 * spikes / len(valid_oee), 1)
    result["spikes_to_1"] = spikes
    result["spikes_to_1_pct"] = spikes_pct
    if spikes == 0:
        result["spike_status"] = "PASS"
    elif spikes < len(valid_oee) * 0.01:
        result["spike_status"] = "OK"
    else:
        result["spike_status"] = "WARN"

    # Timeseries for charting
    valid_rows = prod_summaries[prod_summaries["line_oee"].notna()]
    result["timeseries"] = _to_timeseries(
        valid_rows["timestamp"].tolist(),
        valid_rows["line_oee"].tolist(),
    )

    return result


# ---------------------------------------------------------------------------
# Section 4: Per-Machine OEE
# ---------------------------------------------------------------------------

def analyze_machine_oee(df):
    """Section 4: per-machine OEE stats + timeseries."""
    _require_pandas()
    machine_events = df[
        (df["source_type"] == "machine") & (df["event_type"] == "STATE_CHANGE")
    ]
    machines_list = sorted(machine_events["source"].unique())
    result = {"machines": {}}

    for m in machines_list:
        m_events = machine_events[machine_events["source"] == m]
        m_oee = m_events["oee"].dropna()
        m_data = {"event_count": len(m_events)}

        if len(m_oee) > 0:
            m_data["oee_mean"] = _safe_float(m_oee.mean())
            m_data["oee_median"] = _safe_float(m_oee.median())
            m_data["oee_std"] = _safe_float(m_oee.std())
            m_data["oee_min"] = _safe_float(m_oee.min())
            m_data["oee_max"] = _safe_float(m_oee.max())
            m_data["utilisation_mean"] = _safe_float(m_events["utilisation"].mean())

            last_event = m_events.iloc[-1]
            m_data["last_timestamp"] = _safe_float(last_event["timestamp"])
            m_data["last_partcount"] = int(last_event["partcount"]) if pd.notna(last_event["partcount"]) else None
            m_data["last_good_parts"] = int(last_event["good_parts"]) if pd.notna(last_event["good_parts"]) else None
            defp = last_event["defective_parts"]
            m_data["last_defective_parts"] = int(defp) if pd.notna(defp) else None

            # Timeseries for charting
            m_data["timeseries"] = _to_timeseries(
                m_events["timestamp"].tolist(),
                m_events["oee"].tolist(),
            )
        else:
            m_data["timeseries"] = []

        result["machines"][m] = m_data

    return result


# ---------------------------------------------------------------------------
# Section 5: Failure Analysis
# ---------------------------------------------------------------------------

def analyze_failures(df):
    """Section 5: MTTF, MTTR, failure/repair counts + timeline.

    Tracks hard failures (FAILED/UNDER_REPAIR), degradation events
    (transition into DEGRADED), and maintenance events (ALARM with
    maintenance started/completed messages). This ensures CBM scenarios
    where machines are repaired before reaching FAILED are still captured.
    """
    _require_pandas()
    failures = df[
        (df["event_type"] == "STATE_CHANGE") &
        (df["new_state"].isin(["FAILED", "UNDER_REPAIR"]))
    ]
    repairs = df[
        (df["event_type"] == "STATE_CHANGE") &
        (df["old_state"].isin(["FAILED", "UNDER_REPAIR"])) &
        (~df["new_state"].isin(["FAILED", "UNDER_REPAIR"]))
    ]

    # Degradation events (transition INTO DEGRADED state)
    degradations = df[
        (df["event_type"] == "STATE_CHANGE") &
        (df["source_type"] == "machine") &
        (df["new_state"] == "DEGRADED") &
        (df["old_state"] != "DEGRADED")
    ]

    # Maintenance events from ALARM
    maint_starts = df[
        (df["event_type"] == "ALARM") &
        (df["message"].str.contains("Maintenance started", na=False))
    ]
    maint_ends = df[
        (df["event_type"] == "ALARM") &
        (df["message"].str.contains("Maintenance completed", na=False))
    ]

    machine_events = df[
        (df["source_type"] == "machine") & (df["event_type"] == "STATE_CHANGE")
    ]
    machines_list = sorted(machine_events["source"].unique())
    result = {
        "total_failures": len(failures),
        "total_repairs": len(repairs),
        "total_degradations": len(degradations),
        "total_maintenance_events": len(maint_starts),
        "machines": {},
    }

    for m in machines_list:
        m_failures = failures[failures["source"] == m]
        m_repairs = repairs[repairs["source"] == m]
        m_degradations = degradations[degradations["source"] == m]
        m_maint_starts = maint_starts[maint_starts["source"] == m]
        m_data = {
            "failure_count": len(m_failures),
            "repair_count": len(m_repairs),
            "degradation_count": len(m_degradations),
            "maintenance_count": len(m_maint_starts),
            "failure_timeline": [],
            "degradation_timeline": [],
            "maintenance_timeline": [],
        }

        if len(m_failures) > 1:
            fail_times = m_failures["timestamp"].values
            tbf = [float(fail_times[i + 1] - fail_times[i])
                   for i in range(len(fail_times) - 1)]
            if tbf:
                import statistics
                m_data["mttf_mean"] = round(statistics.mean(tbf), 0)
                m_data["mttf_median"] = round(statistics.median(tbf), 0)

        if len(m_failures) > 0 and len(m_repairs) > 0:
            repair_durations = []
            repair_times = sorted(m_repairs["timestamp"].values)
            for ft in m_failures["timestamp"].values:
                later_repairs = [rt for rt in repair_times if rt > ft]
                if later_repairs:
                    repair_durations.append(float(later_repairs[0] - ft))
            if repair_durations:
                import statistics
                m_data["mttr_mean"] = round(statistics.mean(repair_durations), 1)
                m_data["mttr_median"] = round(statistics.median(repair_durations), 1)

        # Failure timeline for scatter chart
        if len(m_failures) > 0:
            fail_ts = m_failures["timestamp"].tolist()
            fail_vals = [1.0] * len(fail_ts)  # y=1 for failure events
            m_data["failure_timeline"] = _to_timeseries(fail_ts, fail_vals)

        # Degradation timeline for scatter chart
        if len(m_degradations) > 0:
            deg_ts = m_degradations["timestamp"].tolist()
            deg_vals = [0.5] * len(deg_ts)  # y=0.5 for degradation events
            m_data["degradation_timeline"] = _to_timeseries(deg_ts, deg_vals)

        # Maintenance timeline for scatter chart
        if len(m_maint_starts) > 0:
            maint_ts = m_maint_starts["timestamp"].tolist()
            maint_vals = [0.75] * len(maint_ts)  # y=0.75 for maintenance events
            m_data["maintenance_timeline"] = _to_timeseries(maint_ts, maint_vals)

        result["machines"][m] = m_data

    return result


# ---------------------------------------------------------------------------
# Section 6: Quality Routing
# ---------------------------------------------------------------------------

def analyze_quality_routing(df):
    """Section 6: scrap/rework counts per machine."""
    _require_pandas()
    scraps = df[df["event_type"] == "SCRAP"]
    reworks = df[df["event_type"] == "REWORK"]

    machine_events = df[
        (df["source_type"] == "machine") & (df["event_type"] == "STATE_CHANGE")
    ]
    machines_list = sorted(machine_events["source"].unique())

    result = {
        "total_scrap_events": len(scraps),
        "total_rework_events": len(reworks),
        "machines": {},
    }

    for m in machines_list:
        m_scraps = scraps[scraps["source"] == m]
        m_reworks = reworks[reworks["source"] == m]

        if len(m_scraps) == 0 and len(m_reworks) == 0:
            continue

        m_data = {
            "scrap_events": len(m_scraps),
            "rework_events": len(m_reworks),
        }

        if len(m_scraps) > 0:
            last_extra = parse_extra_json(m_scraps.iloc[-1:]["extra_json"]).iloc[0]
            m_data["final_scrap_count"] = last_extra.get("scrap_count", None)

        if len(m_reworks) > 0:
            last_extra = parse_extra_json(m_reworks.iloc[-1:]["extra_json"]).iloc[0]
            m_data["final_rework_count"] = last_extra.get("rework_count", None)
            m_data["rework_success_count"] = last_extra.get("rework_success_count", None)
            rework_total = last_extra.get("rework_count")
            rework_success = last_extra.get("rework_success_count")
            if isinstance(rework_total, (int, float)) and rework_total > 0:
                if isinstance(rework_success, (int, float)):
                    m_data["rework_success_rate"] = round(rework_success / rework_total, 3)

        result["machines"][m] = m_data

    return result


# ---------------------------------------------------------------------------
# Section 7: Shift Analysis
# ---------------------------------------------------------------------------

def analyze_shifts(df):
    """Section 7: shift changes, per-shift production."""
    _require_pandas()
    shifts = df[df["event_type"] == "SHIFT_CHANGE"]
    result = {
        "shift_change_count": len(shifts),
        "shifts": [],
    }

    if len(shifts) > 0:
        shift_extras = parse_extra_json(shifts["extra_json"])
        for _, row in shifts.iterrows():
            extra = shift_extras.loc[row.name]
            result["shifts"].append({
                "timestamp": float(row["timestamp"]),
                "shift_number": int(row["shift_number"]) if pd.notna(row["shift_number"]) else None,
                "shift_name": row["shift_name"] if pd.notna(row["shift_name"]) else None,
                "prev_shift_name": extra.get("prev_shift_name"),
                "prev_shift_parts": extra.get("prev_shift_parts"),
                "prev_shift_oee": extra.get("prev_shift_oee"),
            })

    return result


# ---------------------------------------------------------------------------
# Section 8: Buffer Dynamics
# ---------------------------------------------------------------------------

def analyze_buffer_dynamics(df):
    """Section 8: buffer level stats + timeseries."""
    _require_pandas()
    buf_events = df[
        (df["source_type"] == "buffer") & (df["event_type"] == "STATE_CHANGE")
    ]
    buffers_list = sorted(buf_events["source"].unique())
    result = {"buffers": {}}

    for b in buffers_list:
        b_events = buf_events[buf_events["source"] == b]
        levels = b_events["buffer_level"].dropna()
        b_data = {"event_count": len(b_events)}

        if len(levels) > 0:
            max_level = int(levels.max())
            b_data["level_mean"] = round(float(levels.mean()), 1)
            b_data["level_min"] = int(levels.min())
            b_data["level_max"] = max_level
            b_data["level_std"] = round(float(levels.std()), 1)
            b_data["full_pct"] = round(float((levels == max_level).sum()) / len(levels) * 100, 1)
            b_data["empty_pct"] = round(float((levels == 0).sum()) / len(levels) * 100, 1)

            # Timeseries for charting
            b_data["timeseries"] = _to_timeseries(
                b_events["timestamp"].tolist(),
                b_events["buffer_level"].tolist(),
            )
        else:
            b_data["timeseries"] = []

        result["buffers"][b] = b_data

    return result


# ---------------------------------------------------------------------------
# Section 9: Throughput
# ---------------------------------------------------------------------------

def analyze_throughput(df):
    """Section 9: cumulative throughput + PPM + timeseries."""
    _require_pandas()
    prod_summaries = df[df["event_type"] == "PRODUCTION_SUMMARY"].copy()
    result = {
        "status": "PASS",
        "timeseries": [],
    }

    if len(prod_summaries) <= 1:
        result["status"] = "WARN"
        result["message"] = "Too few production summaries for throughput analysis"
        return result

    first = prod_summaries.iloc[0]
    last = prod_summaries.iloc[-1]
    elapsed = float(last["timestamp"] - first["timestamp"])

    # In recipe mode each segment resets the Simantha system, so partcount
    # resets to 0 at each segment boundary.  Sum parts from SEGMENT_END
    # events which carry the authoritative per-segment total.
    segment_ends = df[df["event_type"] == "SEGMENT_END"]
    is_recipe = not segment_ends.empty

    if is_recipe:
        extras = parse_extra_json(segment_ends["extra_json"])
        total_parts = 0
        for i in range(len(segment_ends)):
            ext = extras.iloc[i] if i < len(extras) else {}
            if isinstance(ext, dict):
                total_parts += int(ext.get("parts_produced", 0))
    else:
        total_parts = int(last["partcount"]) if pd.notna(last["partcount"]) else 0

    if elapsed > 0:
        if is_recipe:
            # For recipes, use total parts over total elapsed time
            # (changeover time is part of elapsed)
            parts_delta = total_parts
        else:
            first_parts = int(first["partcount"]) if pd.notna(first["partcount"]) else 0
            parts_delta = total_parts - first_parts
        ppm = parts_delta / (elapsed / 60)
        result["total_parts"] = total_parts
        result["elapsed_s"] = round(elapsed, 0)
        result["elapsed_hrs"] = round(elapsed / 3600, 1)
        result["ppm"] = round(ppm, 2)
        result["efficiency_pct"] = round(ppm / 60 * 100, 1)

        if is_recipe:
            # Build cumulative timeseries that accounts for segment resets.
            # Detect resets (partcount drops) and add offset to make it
            # monotonically increasing.
            raw_ts = prod_summaries["timestamp"].tolist()
            raw_parts = prod_summaries["partcount"].tolist()
            cum_parts = []
            offset = 0
            prev = 0
            for p in raw_parts:
                val = int(p) if pd.notna(p) else 0
                if val < prev:
                    offset += prev  # segment reset — carry forward
                cum_parts.append(offset + val)
                prev = val
            result["timeseries"] = _to_timeseries(raw_ts, cum_parts)
        else:
            result["timeseries"] = _to_timeseries(
                prod_summaries["timestamp"].tolist(),
                prod_summaries["partcount"].tolist(),
            )
    else:
        result["status"] = "WARN"
        result["message"] = "Zero elapsed time"

    return result


# ---------------------------------------------------------------------------
# Section 10: Anomaly Check
# ---------------------------------------------------------------------------

def analyze_anomalies(df):
    """Section 10: data integrity checks."""
    _require_pandas()
    checks = []

    # Check for negative partcounts
    neg_parts = df[df["partcount"] < 0] if "partcount" in df.columns else pd.DataFrame()
    checks.append({
        "name": "Negative partcount",
        "status": "FAIL" if len(neg_parts) > 0 else "PASS",
        "count": len(neg_parts),
        "message": f"{len(neg_parts)} events with negative partcount" if len(neg_parts) > 0 else "No negative partcounts",
    })

    # Check for OEE > 1.0
    high_oee = df[df["oee"] > 1.001] if "oee" in df.columns else pd.DataFrame()
    checks.append({
        "name": "OEE > 1.0",
        "status": "FAIL" if len(high_oee) > 0 else "PASS",
        "count": len(high_oee),
        "message": f"{len(high_oee)} events with OEE > 1.0" if len(high_oee) > 0 else "No OEE > 1.0",
    })

    # Check for timestamps going backwards
    ts_diff = df["timestamp"].diff()
    backwards = int((ts_diff < 0).sum())
    checks.append({
        "name": "Timestamps backwards",
        "status": "FAIL" if backwards > 0 else "PASS",
        "count": backwards,
        "message": f"{backwards} timestamps go backwards" if backwards > 0 else "Timestamps monotonic",
    })

    # Check for missing expected event types
    expected_types = {"STATE_CHANGE", "PRODUCTION_SUMMARY"}
    actual_types = set(df["event_type"].unique())
    missing = expected_types - actual_types
    checks.append({
        "name": "Required event types",
        "status": "FAIL" if missing else "PASS",
        "count": len(missing),
        "message": f"Missing: {missing}" if missing else "All required types present",
    })

    anomaly_count = sum(1 for c in checks if c["status"] == "FAIL")
    return {
        "checks": checks,
        "anomaly_count": anomaly_count,
        "status": "FAIL" if anomaly_count > 0 else "PASS",
    }


# ---------------------------------------------------------------------------
# Section 11: OEE Sanity Checks
# ---------------------------------------------------------------------------

def analyze_oee_sanity(df):
    """OEE sanity checks: formula validation, part invariants, monotonicity,
    component ranges, machine-to-line consistency, quality-scrap coherence.

    Each check returns PASS/WARN/FAIL with detail message.
    """
    _require_pandas()
    checks = []

    # --- Check 1: Formula validation (A*P*Q ≈ OEE) in PRODUCTION_SUMMARY ---
    prod_summaries = df[df["event_type"] == "PRODUCTION_SUMMARY"].copy()
    if len(prod_summaries) > 0:
        extras = parse_extra_json(prod_summaries["extra_json"])
        formula_violations = 0
        formula_checked = 0
        for idx, extra in extras.items():
            a = extra.get("line_availability")
            p = extra.get("line_performance")
            q = extra.get("line_quality")
            oee = extra.get("line_oee")
            if all(v is not None for v in [a, p, q, oee]):
                formula_checked += 1
                expected = a * p * q
                if abs(oee - expected) > 0.01:
                    formula_violations += 1

        if formula_checked == 0:
            checks.append({
                "name": "OEE formula (A*P*Q=OEE)",
                "status": "WARN",
                "count": 0,
                "message": "No A/P/Q data in production summaries",
            })
        else:
            checks.append({
                "name": "OEE formula (A*P*Q=OEE)",
                "status": "FAIL" if formula_violations > 0 else "PASS",
                "count": formula_violations,
                "message": (f"{formula_violations}/{formula_checked} summaries violate A*P*Q=OEE"
                            if formula_violations > 0
                            else f"All {formula_checked} summaries satisfy A*P*Q=OEE"),
            })
    else:
        checks.append({
            "name": "OEE formula (A*P*Q=OEE)",
            "status": "WARN",
            "count": 0,
            "message": "No production summaries found",
        })

    # --- Check 2: Part count invariant (good + defective == partcount) ---
    machine_events = df[
        (df["source_type"] == "machine") & (df["event_type"] == "STATE_CHANGE")
    ]
    invariant_violations = 0
    invariant_checked = 0
    if len(machine_events) > 0:
        for _, row in machine_events.iterrows():
            pc = row.get("partcount")
            gp = row.get("good_parts")
            dp = row.get("defective_parts")
            if pd.notna(pc) and pd.notna(gp) and pd.notna(dp):
                invariant_checked += 1
                if abs(int(pc) - (int(gp) + int(dp))) > 1:
                    invariant_violations += 1

    checks.append({
        "name": "Part count invariant (good+defective=total)",
        "status": "FAIL" if invariant_violations > 0 else "PASS",
        "count": invariant_violations,
        "message": (f"{invariant_violations}/{invariant_checked} events violate invariant"
                    if invariant_violations > 0
                    else f"All {invariant_checked} events satisfy invariant"),
    })

    # --- Check 3: Partcount monotonicity within shifts ---
    machines_list = sorted(machine_events["source"].unique()) if len(machine_events) > 0 else []
    mono_violations = 0
    for m in machines_list:
        m_events = machine_events[machine_events["source"] == m].sort_values("timestamp")
        pcs = m_events["partcount"].dropna().values
        if len(pcs) > 1:
            # Check if shift_number changes (reset allowed at shift boundary)
            shifts = m_events["shift_number"].values
            for i in range(1, len(pcs)):
                if pcs[i] < pcs[i - 1]:
                    # Only flag if same shift
                    if pd.notna(shifts[i]) and pd.notna(shifts[i - 1]) and shifts[i] == shifts[i - 1]:
                        mono_violations += 1

    checks.append({
        "name": "Partcount monotonicity (within shift)",
        "status": "FAIL" if mono_violations > 0 else "PASS",
        "count": mono_violations,
        "message": (f"{mono_violations} decreases in partcount within a shift"
                    if mono_violations > 0
                    else "Partcounts are monotonically non-decreasing within shifts"),
    })

    # --- Check 4: A, P, Q component ranges [0, 1] ---
    range_violations = 0
    range_checked = 0
    if len(machine_events) > 0:
        extras = parse_extra_json(machine_events["extra_json"])
        for idx, extra in extras.items():
            for comp in ["availability", "performance", "quality"]:
                val = extra.get(comp)
                if val is not None:
                    range_checked += 1
                    if val < -0.001 or val > 1.001:
                        range_violations += 1

    checks.append({
        "name": "OEE component ranges [0,1]",
        "status": "FAIL" if range_violations > 0 else "PASS",
        "count": range_violations,
        "message": (f"{range_violations}/{range_checked} component values out of [0,1]"
                    if range_violations > 0
                    else f"All {range_checked} component values in [0,1]"),
    })

    # --- Check 5: Machine-to-line consistency (line_OEE ≈ min(machine_OEE)) ---
    line_machine_status = "PASS"
    line_machine_msg = "Not enough data"
    if len(prod_summaries) > 0 and len(machine_events) > 0:
        prod_extras = parse_extra_json(prod_summaries["extra_json"])
        line_oee_vals = [e.get("line_oee") for _, e in prod_extras.items() if e.get("line_oee") is not None]

        # Get per-machine final OEE from state changes
        machine_oees = []
        for m in machines_list:
            m_evts = machine_events[machine_events["source"] == m]
            m_oee = m_evts["oee"].dropna()
            if len(m_oee) > 0:
                machine_oees.append(float(m_oee.iloc[-1]))

        if line_oee_vals and machine_oees:
            last_line_oee = line_oee_vals[-1]
            min_machine_oee = min(machine_oees)
            diff = abs(last_line_oee - min_machine_oee)
            if diff < 0.1:
                line_machine_status = "PASS"
                line_machine_msg = (f"Line OEE ({last_line_oee:.3f}) ≈ "
                                    f"min machine OEE ({min_machine_oee:.3f})")
            else:
                line_machine_status = "WARN"
                line_machine_msg = (f"Line OEE ({last_line_oee:.3f}) differs from "
                                    f"min machine OEE ({min_machine_oee:.3f}) by {diff:.3f}")

    checks.append({
        "name": "Machine-to-line OEE consistency",
        "status": line_machine_status,
        "count": 0,
        "message": line_machine_msg,
    })

    # --- Check 6: Quality-scrap coherence ---
    scraps = df[df["event_type"] == "SCRAP"]
    scrap_machines = set(scraps["source"].unique()) if len(scraps) > 0 else set()
    qsc_violations = 0
    qsc_checked = 0
    for m in machines_list:
        if m in scrap_machines:
            qsc_checked += 1
            m_evts = machine_events[machine_events["source"] == m]
            m_extras = parse_extra_json(m_evts["extra_json"])
            # Check last quality value
            last_quality = None
            for _, extra in m_extras.items():
                q = extra.get("quality")
                if q is not None:
                    last_quality = q
            if last_quality is not None and last_quality >= 0.999:
                qsc_violations += 1

    checks.append({
        "name": "Quality-scrap coherence",
        "status": "WARN" if qsc_violations > 0 else "PASS",
        "count": qsc_violations,
        "message": (f"{qsc_violations}/{qsc_checked} machines have scrap but quality=1.0"
                    if qsc_violations > 0
                    else f"All {qsc_checked} machines with scrap show quality<1.0"
                    if qsc_checked > 0
                    else "No machines with scrap events to check"),
    })

    fail_count = sum(1 for c in checks if c["status"] == "FAIL")
    warn_count = sum(1 for c in checks if c["status"] == "WARN")
    if fail_count > 0:
        overall = "FAIL"
    elif warn_count > 0:
        overall = "WARN"
    else:
        overall = "PASS"

    return {
        "checks": checks,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "status": overall,
    }


# ---------------------------------------------------------------------------
# Section 12: Time in State
# ---------------------------------------------------------------------------

# Predefined order for consistent chart coloring
_STATE_ORDER = [
    "PROCESSING", "BLOCKED", "STARVED", "FAILED",
    "UNDER_REPAIR", "DEGRADED", "IDLE", "PAUSED",
]


def analyze_time_in_state(df):
    """Compute per-machine time spent in each state from STATE_CHANGE events.

    Returns dict with 'machines' (machine -> state -> minutes),
    'states' (ordered list of observed states), and 'total_sim_time' (seconds).
    """
    _require_pandas()
    state_changes = df[
        (df["event_type"] == "STATE_CHANGE") & (df["source_type"] == "machine")
    ].copy()

    sim_end = float(df["timestamp"].max())
    result = {"machines": {}, "states": [], "total_sim_time": sim_end}

    if len(state_changes) == 0:
        return result

    machines_list = sorted(state_changes["source"].unique())
    all_states = set()

    for m in machines_list:
        m_events = state_changes[state_changes["source"] == m].sort_values("timestamp")
        state_seconds = {}

        prev_time = 0.0  # sim starts at 0
        prev_state = str(m_events.iloc[0]["old_state"])

        for _, row in m_events.iterrows():
            t = float(row["timestamp"])
            duration = t - prev_time
            if duration > 0 and prev_state:
                state_seconds[prev_state] = state_seconds.get(prev_state, 0.0) + duration
            prev_time = t
            prev_state = str(row["new_state"])

        # Extend last state to sim_end
        if prev_state and sim_end > prev_time:
            remaining = sim_end - prev_time
            state_seconds[prev_state] = state_seconds.get(prev_state, 0.0) + remaining

        # Convert to minutes
        state_minutes = {s: round(v / 60, 2) for s, v in state_seconds.items()}
        result["machines"][m] = state_minutes
        all_states.update(state_seconds.keys())

    # Order states by predefined priority, then alphabetically for unknowns
    ordered = [s for s in _STATE_ORDER if s in all_states]
    extras = sorted(all_states - set(_STATE_ORDER))
    result["states"] = ordered + extras

    return result


# ---------------------------------------------------------------------------
# Full Analysis
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Section 12: Recipe Segment Analysis
# ---------------------------------------------------------------------------


def analyze_recipe_segments(df):
    """Analyze per-segment production metrics from SEGMENT_START/SEGMENT_END events.

    Returns dict with segment_count, segments list, and has_recipe flag.
    """
    _require_pandas()
    result = {"has_recipe": False, "segment_count": 0, "segments": []}

    start_events = df[df["event_type"] == "SEGMENT_START"]
    end_events = df[df["event_type"] == "SEGMENT_END"]

    if start_events.empty:
        return result

    result["has_recipe"] = True
    extras_start = parse_extra_json(start_events["extra_json"])
    extras_end = parse_extra_json(end_events["extra_json"])

    segments = []
    for i, (_, start_row) in enumerate(start_events.iterrows()):
        seg_extra = extras_start.iloc[i] if i < len(extras_start) else {}
        if not isinstance(seg_extra, dict):
            seg_extra = {}

        seg_name = seg_extra.get("segment", f"Segment {i+1}")
        seg_index = seg_extra.get("segment_index", i + 1)
        start_time = start_row["timestamp"]

        # Find matching end event
        end_extra = {}
        end_time = None
        parts = 0
        oee = 0.0
        stop_reason = "unknown"

        if i < len(end_events):
            end_row = end_events.iloc[i]
            end_time = end_row["timestamp"]
            end_extra = extras_end.iloc[i] if i < len(extras_end) else {}
            if not isinstance(end_extra, dict):
                end_extra = {}
            parts = end_extra.get("parts_produced", 0)
            oee = end_extra.get("oee", 0.0)
            stop_reason = end_extra.get("stop_reason", "unknown")

        duration = (end_time - start_time) if end_time is not None else 0
        segments.append({
            "name": seg_name,
            "index": seg_index,
            "start_time": float(start_time),
            "end_time": float(end_time) if end_time is not None else None,
            "duration": float(duration),
            "parts_produced": int(parts),
            "oee": float(oee),
            "stop_reason": stop_reason,
            "stop_mode": seg_extra.get("stop_mode", ""),
            "target_quantity": seg_extra.get("target_quantity"),
            "target_duration": seg_extra.get("target_duration"),
        })

    result["segment_count"] = len(segments)
    result["segments"] = segments
    result["total_parts"] = sum(s["parts_produced"] for s in segments)
    result["total_duration"] = sum(s["duration"] for s in segments)

    # Recipe name from first event
    first_extra = extras_start.iloc[0] if len(extras_start) > 0 else {}
    if isinstance(first_extra, dict):
        result["recipe_name"] = first_extra.get("recipe", "")

    return result


def analyze_changeovers(df):
    """Analyze planned vs actual changeover performance.

    Returns dict with changeover list and summary statistics.
    """
    _require_pandas()
    result = {"has_changeovers": False, "changeovers": [], "summary": {}}

    co_events = df[df["event_type"] == "CHANGEOVER"]
    if co_events.empty:
        return result

    result["has_changeovers"] = True
    extras = parse_extra_json(co_events["extra_json"])

    changeovers = []
    deltas = []
    for i, (_, row) in enumerate(co_events.iterrows()):
        extra = extras.iloc[i] if i < len(extras) else {}
        if not isinstance(extra, dict):
            extra = {}

        planned = extra.get("planned", 0)
        actual = extra.get("actual", 0)
        delta = extra.get("delta", actual - planned)

        changeovers.append({
            "timestamp": float(row["timestamp"]),
            "from_segment": extra.get("from_segment", ""),
            "to_segment": extra.get("to_segment", ""),
            "planned": float(planned),
            "actual": float(actual),
            "delta": float(delta),
            "pct_over": float(delta / planned * 100) if planned > 0 else 0.0,
        })
        deltas.append(delta)

    result["changeovers"] = changeovers

    if deltas:
        result["summary"] = {
            "count": len(deltas),
            "avg_delta": float(sum(deltas) / len(deltas)),
            "worst_changeover": float(max(deltas)),
            "best_changeover": float(min(deltas)),
            "total_planned": float(sum(c["planned"] for c in changeovers)),
            "total_actual": float(sum(c["actual"] for c in changeovers)),
            "total_changeover_time": float(sum(c["actual"] for c in changeovers)),
        }

    return result


def run_full_analysis(df):
    """Run all analysis sections. Returns combined dict."""
    result = {
        "overview": analyze_overview(df),
        "continuity": analyze_continuity(df),
        "oee": analyze_oee(df),
        "machine_oee": analyze_machine_oee(df),
        "failures": analyze_failures(df),
        "quality_routing": analyze_quality_routing(df),
        "shifts": analyze_shifts(df),
        "buffer_dynamics": analyze_buffer_dynamics(df),
        "throughput": analyze_throughput(df),
        "anomalies": analyze_anomalies(df),
        "oee_sanity": analyze_oee_sanity(df),
        "time_in_state": analyze_time_in_state(df),
    }

    # Add recipe analysis if recipe events are present
    recipe_segments = analyze_recipe_segments(df)
    if recipe_segments["has_recipe"]:
        result["recipe_segments"] = recipe_segments
        result["changeovers"] = analyze_changeovers(df)

    return result


# ---------------------------------------------------------------------------
# Section 11: Pipeline Validation (CSV vs InfluxDB)
# ---------------------------------------------------------------------------

def validate_pipeline(df, influx_data):
    """Compare CSV historian ground truth against Telegraf/InfluxDB OPC UA data.

    Returns a dict with checks list and overall verdict.
    """
    _require_pandas()
    checks = []

    # --- Update rate ---
    avg_rate = influx_data.get("avg_update_rate")
    if avg_rate is not None and avg_rate > 0:
        actual_rate = round(1.0 / avg_rate, 2)
        rate_ok = abs(actual_rate - 1.0) < 0.05
        checks.append({
            "name": "Update rate",
            "csv_value": "1.00/sec",
            "telegraf_value": f"{actual_rate:.2f}/sec",
            "status": "PASS" if rate_ok else "FAIL",
        })
    else:
        checks.append({
            "name": "Update rate",
            "csv_value": "1.00/sec",
            "telegraf_value": "N/A",
            "status": "SKIP",
        })

    # --- Throughput comparison ---
    prod_summaries = df[df["event_type"] == "PRODUCTION_SUMMARY"]
    csv_final_partcount = None
    if len(prod_summaries) > 0:
        last_pc = prod_summaries.iloc[-1]["partcount"]
        csv_final_partcount = int(last_pc) if pd.notna(last_pc) else None

    telegraf_throughput = influx_data.get("final_throughput")
    throughput_status = "SKIP"
    if csv_final_partcount is not None and telegraf_throughput is not None:
        diff = abs(csv_final_partcount - telegraf_throughput)
        throughput_status = "PASS" if diff <= 2 else "FAIL"

    checks.append({
        "name": "Final throughput",
        "csv_value": f"{csv_final_partcount:,}" if csv_final_partcount is not None else "N/A",
        "telegraf_value": f"{telegraf_throughput:,}" if telegraf_throughput is not None else "N/A",
        "status": throughput_status,
    })

    # --- OEE comparison ---
    oee_ts = influx_data.get("oee_timeseries", [])
    oee_status = "SKIP"
    csv_oee_mean = None
    telegraf_oee_mean = None

    if len(oee_ts) > 0 and len(prod_summaries) > 0:
        extras = parse_extra_json(prod_summaries["extra_json"])
        csv_oee_vals = extras.apply(lambda x: x.get("line_oee", None))
        csv_oee_vals = pd.to_numeric(csv_oee_vals, errors="coerce").dropna()
        telegraf_oee_vals = [v["value"] for v in oee_ts if v["value"] is not None]

        if len(csv_oee_vals) > 0 and len(telegraf_oee_vals) > 0:
            csv_oee_mean = round(float(csv_oee_vals.mean()), 4)
            telegraf_oee_mean = round(sum(telegraf_oee_vals) / len(telegraf_oee_vals), 4)
            mean_diff = abs(csv_oee_mean - telegraf_oee_mean)
            oee_status = "PASS" if mean_diff < 0.05 else "FAIL"

    checks.append({
        "name": "OEE mean",
        "csv_value": f"{csv_oee_mean:.4f}" if csv_oee_mean is not None else "N/A",
        "telegraf_value": f"{telegraf_oee_mean:.4f}" if telegraf_oee_mean is not None else "N/A",
        "status": oee_status,
    })

    # --- Per-machine PartCount ---
    machine_pcs = influx_data.get("machine_partcounts", {})
    machine_events = df[(df["source_type"] == "machine") & (df["event_type"] == "STATE_CHANGE")]
    csv_machines = sorted(machine_events["source"].unique())

    for i, csv_m in enumerate(csv_machines):
        telegraf_key = f"Machine{i + 1}"
        m_events = machine_events[machine_events["source"] == csv_m]
        csv_pc = None
        if len(m_events) > 0 and pd.notna(m_events.iloc[-1]["partcount"]):
            csv_pc = int(m_events.iloc[-1]["partcount"])
        telegraf_pc = machine_pcs.get(telegraf_key)

        pc_status = "SKIP"
        if csv_pc is not None and telegraf_pc is not None:
            pc_status = "PASS" if abs(csv_pc - telegraf_pc) <= 2 else "FAIL"

        checks.append({
            "name": f"{telegraf_key} PartCount",
            "csv_value": f"{csv_pc:,}" if csv_pc is not None else "N/A",
            "telegraf_value": f"{telegraf_pc:,}" if telegraf_pc is not None else "N/A",
            "status": pc_status,
        })

    # --- Buffer levels ---
    buffer_levels = influx_data.get("buffer_levels", {})
    buf_events = df[(df["source_type"] == "buffer") & (df["event_type"] == "STATE_CHANGE")]
    csv_buffers = sorted(buf_events["source"].unique())

    for i, csv_b in enumerate(csv_buffers):
        telegraf_key = f"Buffer{i + 1}"
        b_events = buf_events[buf_events["source"] == csv_b]
        csv_level = None
        if len(b_events) > 0 and pd.notna(b_events.iloc[-1]["buffer_level"]):
            csv_level = int(b_events.iloc[-1]["buffer_level"])
        telegraf_level = buffer_levels.get(telegraf_key)

        buf_status = "SKIP"
        if csv_level is not None and telegraf_level is not None:
            buf_status = "PASS" if abs(csv_level - telegraf_level) <= 1 else "FAIL"

        checks.append({
            "name": f"{telegraf_key} level",
            "csv_value": str(csv_level) if csv_level is not None else "N/A",
            "telegraf_value": str(telegraf_level) if telegraf_level is not None else "N/A",
            "status": buf_status,
        })

    # --- Data gaps ---
    gaps = influx_data.get("gaps_over_5s", 0)
    gap_status = "PASS" if gaps == 0 else ("PASS" if gaps <= 3 else "FAIL")
    checks.append({
        "name": "Data gaps (>5s)",
        "csv_value": "0",
        "telegraf_value": str(gaps),
        "status": gap_status,
    })

    # --- Verdict ---
    passed = sum(1 for c in checks if c["status"] == "PASS")
    total = sum(1 for c in checks if c["status"] != "SKIP")
    all_passed = passed == total

    return {
        "checks": checks,
        "passed": passed,
        "total": total,
        "verdict": "PASS" if all_passed else "FAIL",
        "telegraf_total_points": influx_data.get("total_points", 0),
        "telegraf_first_simtime": influx_data.get("first_simtime"),
        "telegraf_last_simtime": influx_data.get("last_simtime"),
        "telegraf_avg_update_rate": influx_data.get("avg_update_rate"),
        "telegraf_gaps_over_5s": gaps,
        "telegraf_gap_details": influx_data.get("gap_details", []),
    }


# ---------------------------------------------------------------------------
# Run Index (future multi-run comparison)
# ---------------------------------------------------------------------------

def append_run_index(csv_file, analysis, index_path=None):
    """Auto-append run metadata to run_index.json after analysis.

    Args:
        csv_file: Path to the CSV file that was analyzed.
        analysis: The dict returned by run_full_analysis().
        index_path: Optional path to run_index.json. Defaults to
                     results/historian/run_index.json relative to project root.
    """
    if index_path is None:
        # Infer from csv_file location
        csv_dir = Path(csv_file).parent
        index_path = csv_dir / "run_index.json"

    # Build run metadata
    csv_name = Path(csv_file).name
    # Extract scenario name from filename (pattern: scenario_YYYYMMDD_HHMMSS_events.csv)
    parts = csv_name.rsplit("_events", 1)
    run_id = parts[0] if parts else csv_name.replace(".csv", "")

    # Try to extract scenario from run_id (everything before the date)
    scenario = run_id
    import re
    date_match = re.search(r'_\d{8}_\d{6}$', run_id)
    if date_match:
        scenario = run_id[:date_match.start()]

    overview = analysis.get("overview", {})
    oee = analysis.get("oee", {})
    throughput = analysis.get("throughput", {})
    quality = analysis.get("quality_routing", {})

    entry = {
        "run_id": run_id,
        "scenario": scenario,
        "csv_file": csv_name,
        "total_events": overview.get("total_events"),
        "sim_duration_hrs": overview.get("sim_duration_hrs"),
        "total_parts": throughput.get("total_parts"),
        "line_oee_mean": oee.get("mean"),
        "total_scrap_events": quality.get("total_scrap_events"),
        "total_rework_events": quality.get("total_rework_events"),
        "anomaly_count": analysis.get("anomalies", {}).get("anomaly_count"),
    }

    # Load existing index
    index = []
    index_path = Path(index_path)
    if index_path.exists():
        try:
            with open(index_path, "r") as f:
                index = json.load(f)
        except (json.JSONDecodeError, IOError):
            index = []

    # Check if this run_id already exists
    existing_ids = {e.get("run_id") for e in index}
    if run_id not in existing_ids:
        index.append(entry)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(index_path, "w") as f:
            json.dump(index, f, indent=2)

    return entry
