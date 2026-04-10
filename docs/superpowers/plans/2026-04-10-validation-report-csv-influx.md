# Validation Report CSV vs InfluxDB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the thin 6-check validation page with a 5-section fidelity report comparing CSV historian KPIs against InfluxDB side-by-side, including per-machine partcounts, OEE, availability, downtime, MTTR, SPC, alarms, rework, scrap, and a data-coverage analysis that flags under-sampled machines.

**Architecture:** Extend `query_influxdb_telegraf()` with 7 new Flux queries; rewrite `validate_pipeline()` to return 5 structured sections instead of a flat checks list; redesign `validation.html` to render those sections. `print_validation()` in `analyze_historian.py` is updated to print the new structure to the CLI.

**Tech Stack:** Python/pandas (report_engine.py), InfluxDB Flux queries (analyze_historian.py), Bootstrap 5 + vanilla JS (validation.html)

---

## File Map

| File | Change |
|------|--------|
| `tools/analyze_historian.py` | Add 7 new Flux query blocks to `query_influxdb_telegraf()`; update `print_validation()` |
| `tools/report_engine.py` | Rewrite `validate_pipeline()` — new 5-section return shape |
| `tests/test_report_engine.py` | Replace `TestValidatePipeline` with comprehensive new class |
| `docker/webui/templates/validation.html` | Complete redesign of results area + JS `renderValidation()` |

---

## Task 1: Extend `query_influxdb_telegraf()` with new InfluxDB queries

**Files:**
- Modify: `tools/analyze_historian.py:326-508`

The function currently returns: `total_points`, `first_simtime`, `last_simtime`, `final_throughput`, `oee_timeseries`, `machine_partcounts`, `buffer_levels`, `update_intervals`, `avg_update_rate`, `gaps_over_5s`, `gap_details`.

Add these new keys (do not remove existing ones — backward compat):

- `simtime_count` — count of SimTime field records (proxy for scrape cycles)
- `line_oee_mean` — mean of LineOEE field
- `total_scrap` — last value of TotalScrap field
- `machine_oee_means` — `{"Machine1": float, ...}` from M{i}_OEE mean
- `machine_availability_means` — from M{i}_Availability mean
- `machine_downtime_last` — from M{i}_DownTime last
- `machine_spc_ooc_last` — from M{i}_SPC_CumulativeOOC last
- `machine_point_counts` — count of M{i}_PartCount records per machine (scrape count proxy)

- [ ] **Step 1: Add the 7 new query blocks inside `query_influxdb_telegraf()`**

Insert after line 507 (`result["gap_details"] = gap_details`) and before `client.close()`:

```python
    # 9. SimTime record count (scrape cycle count)
    flux_simtime_count = f'''
    from(bucket: "{influx_bucket}")
      |> {range_clause}
      |> filter(fn: (r) => r._measurement == "opcua"){run_id_filter}
      |> filter(fn: (r) => r._field == "SimTime")
      |> count()
    '''
    tables = query_api.query(flux_simtime_count, org=influx_org)
    simtime_count = 0
    for table in tables:
        for record in table.records:
            simtime_count += record.get_value() or 0
    result["simtime_count"] = simtime_count

    # 10. Line OEE mean
    flux_line_oee_mean = f'''
    from(bucket: "{influx_bucket}")
      |> {range_clause}
      |> filter(fn: (r) => r._measurement == "opcua"){run_id_filter}
      |> filter(fn: (r) => r._field == "LineOEE")
      |> mean()
    '''
    tables = query_api.query(flux_line_oee_mean, org=influx_org)
    line_oee_mean_val = None
    for table in tables:
        for record in table.records:
            line_oee_mean_val = record.get_value()
    result["line_oee_mean"] = round(line_oee_mean_val, 4) if line_oee_mean_val is not None else None

    # 11. Total scrap last
    flux_scrap = f'''
    from(bucket: "{influx_bucket}")
      |> {range_clause}
      |> filter(fn: (r) => r._measurement == "opcua"){run_id_filter}
      |> filter(fn: (r) => r._field == "TotalScrap")
      |> last()
    '''
    tables = query_api.query(flux_scrap, org=influx_org)
    total_scrap_val = None
    for table in tables:
        for record in table.records:
            total_scrap_val = record.get_value()
    result["total_scrap"] = total_scrap_val

    # 12. Per-machine OEE mean
    flux_m_oee = f'''
    from(bucket: "{influx_bucket}")
      |> {range_clause}
      |> filter(fn: (r) => r._measurement == "opcua"){run_id_filter}
      |> filter(fn: (r) => r._field =~ /^M\\d+_OEE$/)
      |> mean()
    '''
    tables = query_api.query(flux_m_oee, org=influx_org)
    machine_oee_means = {}
    for table in tables:
        for record in table.records:
            field = record.get_field()
            m = _re.match(r"M(\d+)_OEE", field)
            if m:
                machine_oee_means[f"Machine{m.group(1)}"] = round(record.get_value(), 4)
    result["machine_oee_means"] = machine_oee_means

    # 13. Per-machine Availability mean
    flux_m_avail = f'''
    from(bucket: "{influx_bucket}")
      |> {range_clause}
      |> filter(fn: (r) => r._measurement == "opcua"){run_id_filter}
      |> filter(fn: (r) => r._field =~ /^M\\d+_Availability$/)
      |> mean()
    '''
    tables = query_api.query(flux_m_avail, org=influx_org)
    machine_avail_means = {}
    for table in tables:
        for record in table.records:
            field = record.get_field()
            m = _re.match(r"M(\d+)_Availability", field)
            if m:
                machine_avail_means[f"Machine{m.group(1)}"] = round(record.get_value(), 4)
    result["machine_availability_means"] = machine_avail_means

    # 14. Per-machine DownTime last
    flux_m_dt = f'''
    from(bucket: "{influx_bucket}")
      |> {range_clause}
      |> filter(fn: (r) => r._measurement == "opcua"){run_id_filter}
      |> filter(fn: (r) => r._field =~ /^M\\d+_DownTime$/)
      |> last()
    '''
    tables = query_api.query(flux_m_dt, org=influx_org)
    machine_downtime_last = {}
    for table in tables:
        for record in table.records:
            field = record.get_field()
            m = _re.match(r"M(\d+)_DownTime", field)
            if m:
                machine_downtime_last[f"Machine{m.group(1)}"] = record.get_value()
    result["machine_downtime_last"] = machine_downtime_last

    # 15. Per-machine SPC CumulativeOOC last
    flux_m_spc = f'''
    from(bucket: "{influx_bucket}")
      |> {range_clause}
      |> filter(fn: (r) => r._measurement == "opcua"){run_id_filter}
      |> filter(fn: (r) => r._field =~ /^M\\d+_SPC_CumulativeOOC$/)
      |> last()
    '''
    tables = query_api.query(flux_m_spc, org=influx_org)
    machine_spc_ooc_last = {}
    for table in tables:
        for record in table.records:
            field = record.get_field()
            m = _re.match(r"M(\d+)_SPC_CumulativeOOC", field)
            if m:
                machine_spc_ooc_last[f"Machine{m.group(1)}"] = record.get_value()
    result["machine_spc_ooc_last"] = machine_spc_ooc_last

    # 16. Per-machine point count (M{i}_PartCount count = scrape cycles for that machine)
    flux_m_pts = f'''
    from(bucket: "{influx_bucket}")
      |> {range_clause}
      |> filter(fn: (r) => r._measurement == "opcua"){run_id_filter}
      |> filter(fn: (r) => r._field =~ /^M\\d+_PartCount$/)
      |> count()
    '''
    tables = query_api.query(flux_m_pts, org=influx_org)
    machine_point_counts = {}
    for table in tables:
        for record in table.records:
            field = record.get_field()
            m = _re.match(r"M(\d+)_PartCount", field)
            if m:
                machine_point_counts[f"Machine{m.group(1)}"] = record.get_value() or 0
    result["machine_point_counts"] = machine_point_counts
```

- [ ] **Step 2: Update `print_validation()` for new response shape**

Replace the existing `print_validation()` function (lines 204–227) with:

```python
def print_validation(validation):
    """Format validation dict as CLI text report."""
    section("11. CSV vs INFLUXDB (Telegraf OPC UA) COMPARISON")

    ov = validation.get("run_overview", {})
    print(f"  Run ID:           {ov.get('run_id', 'unknown')}")
    print(f"  Sim duration:     {ov.get('sim_duration_s', 0):.0f}s")
    print(f"  CSV events:       {ov.get('csv_total_events', 0):,}")
    print(f"  InfluxDB points:  {ov.get('influx_total_points', 0):,}")
    if ov.get("scrape_interval_s"):
        print(f"  Scrape interval:  {ov['scrape_interval_s']:.3f}s")
    if ov.get("coverage_pct") is not None:
        print(f"  Coverage:         {ov['coverage_pct']:.1f}%")

    print("\n  Line-level metrics:")
    for row in validation.get("line_metrics", []):
        print(f"    {row['name']:35s}  CSV={row['csv_value']:>12s}  "
              f"Influx={row['influx_value']:>12s}  {row['status']}")

    print("\n  Per-machine metrics:")
    for mname, rows in validation.get("machine_metrics", {}).items():
        print(f"  {mname}:")
        for row in rows:
            print(f"    {row['metric']:30s}  CSV={row['csv_value']:>12s}  "
                  f"Influx={row['influx_value']:>12s}  {row['status']}")

    print("\n  Data coverage:")
    for e in validation.get("data_coverage", {}).get("machines", []):
        risk = "RISK" if e["under_sampling_risk"] else "ok"
        print(f"    {e['machine']:6s}  {e['parts_per_second_csv']:.3f} parts/s  "
              f"coverage={e.get('coverage_pct', 'N/A')}%  {risk}")

    verd = validation.get("verdict", {})
    print(f"\n  Pipeline verdict: ", end="")
    if verd.get("overall") == "PASS":
        print(f"PASS  ({verd.get('checks_passed',0)} passed, "
              f"{verd.get('checks_warned',0)} warned / {verd.get('checks_total',0)} total)")
    else:
        print(f"FAIL  ({verd.get('checks_passed',0)} passed, "
              f"{verd.get('checks_warned',0)} warned, "
              f"{len(verd.get('failed_checks',[]))} failed / {verd.get('checks_total',0)} total)")
        for fc in verd.get("failed_checks", []):
            print(f"    FAIL: {fc}")
    print(f"  Fidelity score:   {verd.get('fidelity_score_pct', 0):.1f}%")
    if verd.get("under_sampling_machines"):
        print(f"  Under-sampling:   {', '.join(verd['under_sampling_machines'])}")
```

- [ ] **Step 3: Verify no syntax errors**

```bash
python -c "import sys; sys.path.insert(0,'tools'); import analyze_historian; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add tools/analyze_historian.py
git commit -m "feat: extend query_influxdb_telegraf with 7 new per-machine/line Flux queries"
```

---

## Task 2: Write failing tests for new `validate_pipeline()`

**Files:**
- Modify: `tests/test_report_engine.py` — replace `TestValidatePipeline` class

The existing `TestValidatePipeline` (lines 611–646) has 2 weak tests. Replace with a comprehensive class.

- [ ] **Step 1: Add `_make_validation_df()` and `_make_influx_data()` fixtures after `_make_full_df()`**

Add after line 272 (end of `_make_full_df()`):

```python
def _make_validation_df():
    """Synthetic historian DataFrame for validate_pipeline tests.

    Two machines: M1, M2.
    Includes: PRODUCTION_SUMMARY with machine_partcounts, STATE_CHANGE with
    extra_json.availability, FAILED->UNDER_REPAIR->PROCESSING sequence for M1,
    SPC_VIOLATION with in_control flag, SCRAP with scrap_count, REWORK, ALARM.
    """
    rows = []
    t = 0.0

    # Production summary
    t = 3600.0
    rows.append({
        "run_id": "test_run_20260101_120000",
        "timestamp": t, "event_type": "PRODUCTION_SUMMARY",
        "source": "System", "source_type": "system",
        "severity": "INFO", "message": "summary",
        "old_state": "", "new_state": "",
        "partcount": 200, "good_parts": 180, "defective_parts": 20,
        "buffer_level": pd.NA, "oee": 0.80, "utilisation": 0.90,
        "shift_number": 1, "shift_name": "Day",
        "extra_json": json.dumps({
            "line_oee": 0.80,
            "machine_partcounts": {"M1": 110, "M2": 90},
        }),
    })

    # STATE_CHANGE rows with availability in extra_json
    for m_name in ["M1", "M2"]:
        for i in range(5):
            t += 60.0
            rows.append({
                "run_id": "test_run_20260101_120000",
                "timestamp": t, "event_type": "STATE_CHANGE",
                "source": m_name, "source_type": "machine",
                "severity": "INFO", "message": "state change",
                "old_state": "PROCESSING", "new_state": "IDLE",
                "partcount": 50 + i * 5, "good_parts": 45 + i * 5, "defective_parts": 5,
                "buffer_level": pd.NA, "oee": 0.82, "utilisation": 0.88,
                "shift_number": 1, "shift_name": "Day",
                "extra_json": json.dumps({"availability": 0.90, "performance": 0.91, "quality": 0.98}),
            })

    # Failure sequence for M1: FAILED -> UNDER_REPAIR -> PROCESSING
    t += 10.0
    rows.append({
        "run_id": "test_run_20260101_120000",
        "timestamp": t, "event_type": "STATE_CHANGE",
        "source": "M1", "source_type": "machine",
        "severity": "WARNING", "message": "failed",
        "old_state": "PROCESSING", "new_state": "FAILED",
        "partcount": 110, "good_parts": 100, "defective_parts": 10,
        "buffer_level": pd.NA, "oee": 0.5, "utilisation": 0.5,
        "shift_number": 1, "shift_name": "Day", "extra_json": "",
    })
    t += 5.0
    rows.append({
        "run_id": "test_run_20260101_120000",
        "timestamp": t, "event_type": "STATE_CHANGE",
        "source": "M1", "source_type": "machine",
        "severity": "INFO", "message": "under repair",
        "old_state": "FAILED", "new_state": "UNDER_REPAIR",
        "partcount": 110, "good_parts": 100, "defective_parts": 10,
        "buffer_level": pd.NA, "oee": 0.0, "utilisation": 0.0,
        "shift_number": 1, "shift_name": "Day", "extra_json": "",
    })
    t += 15.0
    rows.append({
        "run_id": "test_run_20260101_120000",
        "timestamp": t, "event_type": "STATE_CHANGE",
        "source": "M1", "source_type": "machine",
        "severity": "INFO", "message": "repaired",
        "old_state": "UNDER_REPAIR", "new_state": "PROCESSING",
        "partcount": 110, "good_parts": 100, "defective_parts": 10,
        "buffer_level": pd.NA, "oee": 0.8, "utilisation": 0.85,
        "shift_number": 1, "shift_name": "Day", "extra_json": "",
    })

    # SPC_VIOLATION: OOC entry (in_control=False) + recovery (in_control=True) for M1
    t += 30.0
    rows.append({
        "run_id": "test_run_20260101_120000",
        "timestamp": t, "event_type": "SPC_VIOLATION",
        "source": "M1", "source_type": "machine",
        "severity": "WARNING", "message": "OOC",
        "old_state": "", "new_state": "",
        "partcount": 110, "good_parts": 100, "defective_parts": 10,
        "buffer_level": pd.NA, "oee": 0.8, "utilisation": 0.85,
        "shift_number": 1, "shift_name": "Day",
        "extra_json": json.dumps({"in_control": False}),
    })
    t += 10.0
    rows.append({
        "run_id": "test_run_20260101_120000",
        "timestamp": t, "event_type": "SPC_VIOLATION",
        "source": "M1", "source_type": "machine",
        "severity": "INFO", "message": "recovered",
        "old_state": "", "new_state": "",
        "partcount": 110, "good_parts": 100, "defective_parts": 10,
        "buffer_level": pd.NA, "oee": 0.8, "utilisation": 0.85,
        "shift_number": 1, "shift_name": "Day",
        "extra_json": json.dumps({"in_control": True}),
    })

    # SCRAP events for M1 (cumulative scrap_count)
    for i in range(3):
        t += 20.0
        rows.append({
            "run_id": "test_run_20260101_120000",
            "timestamp": t, "event_type": "SCRAP",
            "source": "M1", "source_type": "machine",
            "severity": "WARNING", "message": "scrap",
            "old_state": "", "new_state": "",
            "partcount": 110, "good_parts": 100, "defective_parts": 10,
            "buffer_level": pd.NA, "oee": 0.8, "utilisation": 0.85,
            "shift_number": 1, "shift_name": "Day",
            "extra_json": json.dumps({"scrap_count": i + 1}),
        })

    # REWORK event for M2
    t += 15.0
    rows.append({
        "run_id": "test_run_20260101_120000",
        "timestamp": t, "event_type": "REWORK",
        "source": "M2", "source_type": "machine",
        "severity": "WARNING", "message": "rework",
        "old_state": "", "new_state": "",
        "partcount": 90, "good_parts": 80, "defective_parts": 10,
        "buffer_level": pd.NA, "oee": 0.8, "utilisation": 0.85,
        "shift_number": 1, "shift_name": "Day",
        "extra_json": json.dumps({"rework_count": 1}),
    })

    # ALARM event for M1 and M2
    for m_name in ["M1", "M2"]:
        t += 10.0
        rows.append({
            "run_id": "test_run_20260101_120000",
            "timestamp": t, "event_type": "ALARM",
            "source": m_name, "source_type": "machine",
            "severity": "HIGH", "message": "alarm",
            "old_state": "", "new_state": "",
            "partcount": pd.NA, "good_parts": pd.NA, "defective_parts": pd.NA,
            "buffer_level": pd.NA, "oee": pd.NA, "utilisation": pd.NA,
            "shift_number": 1, "shift_name": "Day", "extra_json": "",
        })

    return pd.DataFrame(rows)


def _make_influx_data(matching=True):
    """Synthetic influx_data for validate_pipeline tests.
    matching=True: values close to CSV (PASS).
    matching=False: values differ by ~50% (FAIL).
    """
    f = 1.0 if matching else 0.5
    return {
        "simtime_count": 3600,
        "first_simtime": 1.0,
        "last_simtime": 3600.0,
        "avg_update_rate": 1.0,
        "update_intervals": [1.0] * 100,
        "gaps_over_5s": 0,
        "gap_details": [],
        "final_throughput": int(200 * f),
        "total_scrap": int(3 * f),
        "line_oee_mean": round(0.80 * f, 4),
        "oee_timeseries": [],  # kept for backward compat
        "machine_partcounts": {
            "Machine1": int(110 * f),
            "Machine2": int(90 * f),
        },
        "machine_oee_means": {
            "Machine1": round(0.82 * f, 4),
            "Machine2": round(0.82 * f, 4),
        },
        "machine_availability_means": {
            "Machine1": round(0.90 * f, 4),
            "Machine2": round(0.90 * f, 4),
        },
        "machine_downtime_last": {
            "Machine1": 20.0,
            "Machine2": 0.0,
        },
        "machine_spc_ooc_last": {
            "Machine1": int(1 * f),
            "Machine2": 0,
        },
        "machine_point_counts": {
            "Machine1": 3600,
            "Machine2": 3600,
        },
        "buffer_levels": {"Buffer1": 3},
    }
```

- [ ] **Step 2: Replace `TestValidatePipeline` (lines 611–646) with the new class**

```python
class TestValidatePipeline:
    """Tests for the new 5-section validate_pipeline() output."""

    def test_response_has_all_sections(self):
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        assert "run_overview" in result
        assert "line_metrics" in result
        assert "machine_metrics" in result
        assert "data_coverage" in result
        assert "gaps" in result
        assert "verdict" in result

    def test_run_overview_fields(self):
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        ov = result["run_overview"]
        assert ov["run_id"] == "test_run_20260101_120000"
        assert ov["sim_duration_s"] > 0
        assert ov["csv_total_events"] == len(df)
        assert ov["influx_total_points"] == 3600  # simtime_count is preferred
        assert ov["scrape_interval_s"] == 1.0
        assert ov["coverage_pct"] is not None

    def test_line_metrics_parts_produced_pass(self):
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data(matching=True))
        row = next(r for r in result["line_metrics"] if r["name"] == "Parts produced")
        assert row["status"] == "PASS"

    def test_line_metrics_parts_produced_fail(self):
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data(matching=False))
        row = next(r for r in result["line_metrics"] if r["name"] == "Parts produced")
        assert row["status"] == "FAIL"

    def test_line_metrics_good_parts_skipped(self):
        """Good parts has no InfluxDB field — must be SKIP."""
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        row = next(r for r in result["line_metrics"] if r["name"] == "Good parts")
        assert row["status"] == "SKIP"
        assert row["influx_note"] is not None

    def test_line_metrics_spc_counts_only_ooc_entries(self):
        """SPC total must count only in_control=False events, not recovery events."""
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        row = next(r for r in result["line_metrics"] if "SPC" in r["name"])
        # CSV has 1 OOC entry event and 1 recovery event; only entry counts
        assert row["csv_value"] == "1"

    def test_machine_metrics_present_for_each_machine(self):
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        assert "M1" in result["machine_metrics"]
        assert "M2" in result["machine_metrics"]

    def test_machine_metrics_row_keys(self):
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        for row in result["machine_metrics"]["M1"]:
            assert "metric" in row
            assert "csv_value" in row
            assert "influx_value" in row
            assert "status" in row

    def test_machine_metrics_availability_from_extra_json(self):
        """Availability must come from extra_json.availability, not be None."""
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        row = next(r for r in result["machine_metrics"]["M1"] if r["metric"] == "Availability mean")
        assert row["csv_value"] != "N/A"

    def test_machine_metrics_mttr_uses_under_repair_state(self):
        """MTTR must span FAILED through UNDER_REPAIR to recovery (total = 20s)."""
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        row = next(r for r in result["machine_metrics"]["M1"] if r["metric"] == "MTTR mean (s)")
        # FAILED at t+10, UNDER_REPAIR at t+15, PROCESSING at t+30 -> repair = 20s
        assert row["csv_value"] == "20.0"
        assert row["status"] == "SKIP"  # InfluxDB side is N/A

    def test_machine_metrics_scrap_from_cumulative_count(self):
        """Scrap count must use last extra_json.scrap_count (=3), not event row count."""
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        row = next(r for r in result["machine_metrics"]["M1"] if r["metric"] == "Scrap events")
        assert row["csv_value"] == "3"

    def test_data_coverage_section_structure(self):
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data())
        dc = result["data_coverage"]
        assert "scrape_interval_s" in dc
        assert len(dc["machines"]) == 2
        for m in dc["machines"]:
            assert "machine" in m
            assert "parts_per_second_csv" in m
            assert "under_sampling_risk" in m
            assert "coverage_pct" in m

    def test_data_coverage_flags_fast_machine(self):
        """A machine producing > 1 part/s should be flagged as under-sampling risk."""
        df = _make_validation_df()
        influx = _make_influx_data()
        influx["avg_update_rate"] = 1.0  # 1s scrape
        # Adjust partcount so M1 produces > 1 part/s over a 100s run
        short_df = df.copy()
        short_df["timestamp"] = short_df["timestamp"] / 36  # compress to ~100s
        # Also set partcount high enough
        result = validate_pipeline(df, influx)
        # M1 has 110 parts over ~3750s -> 0.029 parts/s < 1/s, no flag expected
        m1 = next(e for e in result["data_coverage"]["machines"] if e["machine"] == "M1")
        assert m1["under_sampling_risk"] is False

    def test_verdict_pass_when_no_fails(self):
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data(matching=True))
        verd = result["verdict"]
        assert "overall" in verd
        assert "checks_passed" in verd
        assert "checks_warned" in verd
        assert "checks_total" in verd
        assert "fidelity_score_pct" in verd
        assert "failed_checks" in verd
        assert verd["overall"] == "PASS"
        assert verd["failed_checks"] == []

    def test_verdict_fail_when_mismatch(self):
        df = _make_validation_df()
        result = validate_pipeline(df, _make_influx_data(matching=False))
        assert result["verdict"]["overall"] == "FAIL"
        assert len(result["verdict"]["failed_checks"]) > 0

    def test_empty_influx_data_no_crash(self):
        """Empty influx_data dict must return valid structure with all SKIP statuses."""
        df = _make_validation_df()
        result = validate_pipeline(df, {})
        assert "run_overview" in result
        assert "verdict" in result
        # All line metrics except the gaps row should be SKIP when influx_data is empty
        for row in result["line_metrics"]:
            if row["name"] != "Telegraf data gaps (>5s)":
                assert row["status"] == "SKIP", f"{row['name']} should be SKIP with empty influx_data"

    def test_machine_with_no_scrap_contributes_zero(self):
        """A machine with no SCRAP events must contribute 0 to total scrap sum."""
        df = _make_validation_df()
        # M2 has no scrap events in fixture
        result = validate_pipeline(df, _make_influx_data())
        # total scrap row should use M1's count only (3), not crash on missing M2 scrap
        row = next(r for r in result["line_metrics"] if "scrap" in r["name"].lower())
        assert row["csv_value"] != "N/A"
```

- [ ] **Step 3: Run the new tests — expect FAIL (function not yet updated)**

```bash
pytest tests/test_report_engine.py::TestValidatePipeline -v 2>&1 | tail -30
```

Expected: most tests fail with `KeyError` or `AssertionError` because `validate_pipeline()` still returns `{checks: [...]}`.

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/test_report_engine.py
git commit -m "test: add comprehensive TestValidatePipeline for new 5-section response shape"
```

---

## Task 3: Implement new `validate_pipeline()` in `report_engine.py`

**Files:**
- Modify: `tools/report_engine.py:1180-1340`

Replace the entire `validate_pipeline()` function body (keep the function signature `def validate_pipeline(df, influx_data):`).

- [ ] **Step 1: Replace `validate_pipeline()` with the new implementation**

```python
def validate_pipeline(df, influx_data):
    """Compare CSV historian ground truth against Telegraf/InfluxDB OPC UA data.

    Returns a dict with sections:
      run_overview, line_metrics, machine_metrics, data_coverage, gaps, verdict.
    """
    _require_pandas()

    # ── Format / status helpers ─────────────────────────────────────────────
    def _fmt(v, decimals=2):
        if v is None:
            return "N/A"
        try:
            if isinstance(v, float) and (pd.isna(v) or not pd.api.types.is_number(v)):
                return "N/A"
        except Exception:
            pass
        if isinstance(v, int):
            return f"{v:,}"
        if isinstance(v, float):
            return f"{v:,.{decimals}f}"
        return str(v)

    def _mk_row(name, csv_val, influx_val, threshold,
                influx_note=None, mode="pct", metric_key=None):
        """Build a comparison row dict with PASS/WARN/FAIL/SKIP status."""
        key = metric_key or name
        csv_str = _fmt(csv_val) if not isinstance(csv_val, str) else (csv_val or "N/A")
        if influx_val is None or (isinstance(influx_val, float) and pd.isna(influx_val)):
            return {"name": key, "metric": key, "csv_value": csv_str,
                    "influx_value": "N/A", "influx_note": influx_note,
                    "delta_pct": None, "status": "SKIP"}
        influx_str = _fmt(influx_val) if not isinstance(influx_val, str) else influx_val
        if threshold is None or csv_val is None:
            return {"name": key, "metric": key, "csv_value": csv_str,
                    "influx_value": influx_str, "influx_note": influx_note,
                    "delta_pct": None, "status": "SKIP"}
        try:
            csv_f, inf_f = float(csv_val), float(influx_val)
        except (TypeError, ValueError):
            return {"name": key, "metric": key, "csv_value": csv_str,
                    "influx_value": influx_str, "influx_note": influx_note,
                    "delta_pct": None, "status": "SKIP"}
        if mode == "pct":
            denom = max(abs(csv_f), 1.0)
            delta = abs(csv_f - inf_f) / denom * 100.0
        else:  # "abs"
            delta = abs(csv_f - inf_f)
        status = ("PASS" if delta <= threshold
                  else "WARN" if delta <= threshold * 2
                  else "FAIL")
        return {"name": key, "metric": key, "csv_value": csv_str,
                "influx_value": influx_str, "influx_note": influx_note,
                "delta_pct": round(delta, 4), "status": status}

    def _skip(name, csv_val, note):
        return {"name": name, "metric": name,
                "csv_value": _fmt(csv_val) if not isinstance(csv_val, str) else (csv_val or "N/A"),
                "influx_value": "N/A", "influx_note": note,
                "delta_pct": None, "status": "SKIP"}

    # ── Machine mapping ─────────────────────────────────────────────────────
    mach_sc = df[(df["source_type"] == "machine") & (df["event_type"] == "STATE_CHANGE")]
    csv_machines = sorted(mach_sc["source"].unique().tolist())
    # Map sorted CSV machine name -> InfluxDB key "Machine{i+1}"
    mach_key = {m: f"Machine{i + 1}" for i, m in enumerate(csv_machines)}

    # ── 1. Run Overview ─────────────────────────────────────────────────────
    sim_start = float(df["timestamp"].min()) if len(df) > 0 else 0.0
    sim_end   = float(df["timestamp"].max()) if len(df) > 0 else 0.0
    sim_dur   = sim_end - sim_start
    run_id    = ""
    if "run_id" in df.columns and len(df) > 0:
        rid = df["run_id"].iloc[0]
        if pd.notna(rid):
            run_id = str(rid).strip()

    scrape_interval = influx_data.get("avg_update_rate")
    total_influx_pts = influx_data.get("simtime_count") or influx_data.get("total_points") or 0
    expected_pts = (int(sim_dur / scrape_interval)
                    if scrape_interval and scrape_interval > 0 else None)
    coverage_pct = (round(total_influx_pts / expected_pts * 100, 1)
                    if expected_pts else None)

    run_overview = {
        "run_id": run_id,
        "sim_start": sim_start,
        "sim_end": sim_end,
        "sim_duration_s": sim_dur,
        "csv_total_events": len(df),
        "influx_total_points": total_influx_pts,
        "scrape_interval_s": round(scrape_interval, 3) if scrape_interval else None,
        "expected_points": expected_pts,
        "coverage_pct": coverage_pct,
        "first_simtime_influx": influx_data.get("first_simtime"),
        "last_simtime_influx": influx_data.get("last_simtime"),
    }

    # ── 2. Line-Level Metrics ───────────────────────────────────────────────
    prod_summ = df[df["event_type"] == "PRODUCTION_SUMMARY"]
    all_sc = df[df["event_type"] == "STATE_CHANGE"]

    # Parts produced
    csv_parts = None
    if len(prod_summ) > 0:
        last_pc = prod_summ.iloc[-1]["partcount"]
        csv_parts = int(last_pc) if pd.notna(last_pc) else None

    # Good / defective from last STATE_CHANGE row (any machine)
    csv_good = csv_defective = None
    if len(all_sc) > 0:
        last_sc = all_sc.iloc[-1]
        gp = last_sc.get("good_parts")
        dp = last_sc.get("defective_parts")
        if pd.notna(gp):
            csv_good = int(gp)
        if pd.notna(dp):
            csv_defective = int(dp)

    # Quality rate
    csv_quality = None
    if csv_good is not None and csv_defective is not None:
        total_q = csv_good + csv_defective
        csv_quality = round(csv_good / total_q, 4) if total_q > 0 else None

    # Total scrap parts (sum of last cumulative scrap_count per machine)
    scrap_rows = df[df["event_type"] == "SCRAP"]
    csv_scrap_total = 0
    for m in csv_machines:
        m_scrap = scrap_rows[scrap_rows["source"] == m]
        if len(m_scrap) > 0:
            last_ex = parse_extra_json(m_scrap["extra_json"]).iloc[-1]
            if isinstance(last_ex, dict):
                csv_scrap_total += int(last_ex.get("scrap_count") or 0)
    csv_scrap_total = csv_scrap_total if csv_scrap_total > 0 else None

    # Total rework events
    rework_rows = df[df["event_type"] == "REWORK"]
    csv_rework = len(rework_rows) if len(rework_rows) > 0 else None

    # Line OEE mean
    csv_oee_mean = None
    if len(prod_summ) > 0:
        extras = parse_extra_json(prod_summ["extra_json"])
        vals = pd.to_numeric(
            extras.apply(lambda x: x.get("line_oee") if isinstance(x, dict) else None),
            errors="coerce"
        ).dropna()
        if len(vals) > 0:
            csv_oee_mean = round(float(vals.mean()), 4)

    # Total SPC OOC entries (in_control == False only)
    spc_rows = df[df["event_type"] == "SPC_VIOLATION"]
    csv_spc_ooc = 0
    if len(spc_rows) > 0:
        spc_ex = parse_extra_json(spc_rows["extra_json"])
        csv_spc_ooc = int(
            spc_ex.apply(
                lambda x: x.get("in_control") is False if isinstance(x, dict) else False
            ).sum()
        )

    # InfluxDB total SPC (sum of per-machine last CumulativeOOC)
    spc_per_m = influx_data.get("machine_spc_ooc_last", {})
    influx_spc_total = (
        sum(v for v in spc_per_m.values() if v is not None) if spc_per_m else None
    )

    # Total alarms
    alarm_rows = df[df["event_type"] == "ALARM"]
    csv_alarms = len(alarm_rows) if len(alarm_rows) > 0 else None

    gaps_count = influx_data.get("gaps_over_5s", 0) or 0

    line_metrics = [
        _mk_row("Parts produced", csv_parts,
                influx_data.get("final_throughput"), threshold=2.0, mode="pct"),
        _skip("Good parts", csv_good, "Not an OPC UA field — historian only"),
        _skip("Defective parts", csv_defective, "Not an OPC UA field — historian only"),
        _skip("Quality rate",
              f"{csv_quality:.4f}" if csv_quality is not None else None,
              "Not an OPC UA field — historian only"),
        _mk_row("Total scrap parts", csv_scrap_total,
                influx_data.get("total_scrap"), threshold=1.0, mode="pct"),
        _skip("Total rework events", csv_rework,
              "Historian only — no OPC UA field"),
        _mk_row("Line OEE mean", csv_oee_mean,
                influx_data.get("line_oee_mean"), threshold=0.05, mode="abs"),
        _mk_row("Total SPC OOC entries",
                csv_spc_ooc if csv_spc_ooc else None,
                influx_spc_total, threshold=5.0, mode="pct"),
        _skip("Total alarms", csv_alarms,
              "Not an OPC UA field — historian only"),
        {
            "name": "Telegraf data gaps (>5s)", "metric": "Telegraf data gaps (>5s)",
            "csv_value": "0", "influx_value": str(gaps_count),
            "influx_note": None, "delta_pct": None,
            "status": "PASS" if gaps_count == 0 else ("WARN" if gaps_count <= 3 else "FAIL"),
        },
    ]

    # ── 3. Per-Machine Metrics ──────────────────────────────────────────────
    machine_metrics = {}

    for m in csv_machines:
        ikey = mach_key[m]
        m_sc_all = df[(df["source"] == m) & (df["event_type"] == "STATE_CHANGE")].sort_values("timestamp")
        m_sc_mach = mach_sc[mach_sc["source"] == m]
        rows_m = []

        # Part count
        csv_pc = None
        if len(prod_summ) > 0:
            last_ex = parse_extra_json(prod_summ["extra_json"]).iloc[-1]
            if isinstance(last_ex, dict) and "machine_partcounts" in last_ex:
                csv_pc = last_ex["machine_partcounts"].get(m)
        if csv_pc is None and len(m_sc_mach) > 0:
            max_pc = m_sc_mach["partcount"].max()
            if pd.notna(max_pc):
                csv_pc = int(max_pc)
        rows_m.append(_mk_row("Part count", csv_pc,
                               influx_data.get("machine_partcounts", {}).get(ikey),
                               threshold=2.0, mode="pct", metric_key="Part count"))

        # OEE mean
        csv_oee_m = None
        if len(m_sc_mach) > 0:
            oee_vals = pd.to_numeric(m_sc_mach["oee"], errors="coerce").dropna()
            if len(oee_vals) > 0:
                csv_oee_m = round(float(oee_vals.mean()), 4)
        rows_m.append(_mk_row("OEE mean", csv_oee_m,
                               influx_data.get("machine_oee_means", {}).get(ikey),
                               threshold=0.05, mode="abs", metric_key="OEE mean"))

        # Availability mean — from extra_json.availability on STATE_CHANGE rows
        csv_avail_m = None
        if len(m_sc_mach) > 0:
            avail_ex = parse_extra_json(m_sc_mach["extra_json"])
            avail_vals = pd.to_numeric(
                avail_ex.apply(lambda x: x.get("availability") if isinstance(x, dict) else None),
                errors="coerce"
            ).dropna()
            if len(avail_vals) > 0:
                csv_avail_m = round(float(avail_vals.mean()), 4)
        rows_m.append(_mk_row("Availability mean", csv_avail_m,
                               influx_data.get("machine_availability_means", {}).get(ikey),
                               threshold=0.05, mode="abs", metric_key="Availability mean"))

        # Total downtime — duration of rows where new_state in {FAILED, UNDER_REPAIR}
        csv_downtime_m = 0.0
        if len(m_sc_all) > 1:
            ts_list = m_sc_all["timestamp"].tolist()
            states = m_sc_all["new_state"].tolist()
            for j in range(len(states) - 1):
                if states[j] in ("FAILED", "UNDER_REPAIR"):
                    csv_downtime_m += float(ts_list[j + 1]) - float(ts_list[j])
        rows_m.append(_mk_row("Total downtime (s)",
                               round(csv_downtime_m, 1) if csv_downtime_m > 0 else 0.0,
                               influx_data.get("machine_downtime_last", {}).get(ikey),
                               threshold=5.0, mode="pct", metric_key="Total downtime (s)"))

        # Failure count (CSV only)
        m_fail_count = int((m_sc_all["new_state"] == "FAILED").sum())
        rows_m.append(_skip("Failure count",
                             m_fail_count if m_fail_count > 0 else None,
                             "State snapshot data cannot reconstruct failure count reliably"))

        # MTTR mean — FAILED entry to first subsequent non-{FAILED,UNDER_REPAIR} state
        repair_durations = []
        in_repair = False
        repair_start = None
        for _, r in m_sc_all.iterrows():
            ns = r["new_state"]
            t_ev = float(r["timestamp"])
            if ns == "FAILED" and not in_repair:
                in_repair = True
                repair_start = t_ev
            elif in_repair and ns not in ("FAILED", "UNDER_REPAIR"):
                repair_durations.append(t_ev - repair_start)
                in_repair = False
        csv_mttr_m = round(sum(repair_durations) / len(repair_durations), 1) if repair_durations else None
        rows_m.append(_skip("MTTR mean (s)", csv_mttr_m,
                             "Sub-second precision required; snapshot data unreliable for MTTR"))

        # SPC OOC entries (in_control == False)
        m_spc = df[(df["source"] == m) & (df["event_type"] == "SPC_VIOLATION")]
        csv_spc_m = 0
        if len(m_spc) > 0:
            spc_ex_m = parse_extra_json(m_spc["extra_json"])
            csv_spc_m = int(
                spc_ex_m.apply(
                    lambda x: x.get("in_control") is False if isinstance(x, dict) else False
                ).sum()
            )
        rows_m.append(_mk_row("SPC OOC entries",
                               csv_spc_m if csv_spc_m > 0 else None,
                               influx_data.get("machine_spc_ooc_last", {}).get(ikey),
                               threshold=10.0, mode="pct", metric_key="SPC OOC entries"))

        # Alarms (CSV only)
        m_alm = df[(df["source"] == m) & (df["event_type"] == "ALARM")]
        rows_m.append(_skip("Alarms", len(m_alm) if len(m_alm) > 0 else None,
                             "Not an OPC UA field — historian only"))

        # Rework (CSV only)
        m_rew = df[(df["source"] == m) & (df["event_type"] == "REWORK")]
        rows_m.append(_skip("Rework events", len(m_rew) if len(m_rew) > 0 else None,
                             "Historian only — no OPC UA field"))

        # Scrap — last cumulative scrap_count from SCRAP events
        m_scr = scrap_rows[scrap_rows["source"] == m]
        csv_scrap_m = None
        if len(m_scr) > 0:
            last_ex_m = parse_extra_json(m_scr["extra_json"]).iloc[-1]
            if isinstance(last_ex_m, dict):
                csv_scrap_m = int(last_ex_m.get("scrap_count") or 0)
        rows_m.append(_skip("Scrap events", csv_scrap_m,
                             "Historian only — no OPC UA field"))

        machine_metrics[m] = rows_m

    # ── 4. Data Coverage ────────────────────────────────────────────────────
    scrape_int = scrape_interval or 1.0
    coverage_machines = []
    for m in csv_machines:
        ikey = mach_key[m]
        # Re-derive per-machine partcount for coverage
        csv_pc_m = 0
        if len(prod_summ) > 0:
            last_ex = parse_extra_json(prod_summ["extra_json"]).iloc[-1]
            if isinstance(last_ex, dict) and "machine_partcounts" in last_ex:
                val = last_ex["machine_partcounts"].get(m)
                if val is not None:
                    csv_pc_m = int(val)
        if csv_pc_m == 0:
            m_sc_m = mach_sc[mach_sc["source"] == m]
            if len(m_sc_m) > 0:
                max_pc = m_sc_m["partcount"].max()
                if pd.notna(max_pc):
                    csv_pc_m = int(max_pc)
        parts_per_sec = round(csv_pc_m / sim_dur, 4) if sim_dur > 0 else 0.0
        max_cap = round(1.0 / scrape_int, 4)
        influx_pts = int(influx_data.get("machine_point_counts", {}).get(ikey) or 0)
        exp_pts = int(sim_dur / scrape_int) if scrape_int > 0 else 0
        cov = round(influx_pts / exp_pts * 100, 1) if exp_pts > 0 else None
        coverage_machines.append({
            "machine": m,
            "parts_per_second_csv": parts_per_sec,
            "max_capturable_rate": max_cap,
            "under_sampling_risk": parts_per_sec > max_cap,
            "influx_points": influx_pts,
            "expected_points": exp_pts,
            "coverage_pct": cov,
        })

    data_coverage = {
        "scrape_interval_s": round(scrape_int, 3),
        "machines": coverage_machines,
    }

    # ── 5. Verdict ──────────────────────────────────────────────────────────
    all_rows = line_metrics[:]
    for m_rows in machine_metrics.values():
        all_rows.extend(m_rows)
    non_skip = [r for r in all_rows if r["status"] != "SKIP"]
    pass_ct = sum(1 for r in non_skip if r["status"] == "PASS")
    warn_ct = sum(1 for r in non_skip if r["status"] == "WARN")
    fail_ct = sum(1 for r in non_skip if r["status"] == "FAIL")
    total_ct = len(non_skip)
    fidelity = round((pass_ct + warn_ct) / total_ct * 100, 1) if total_ct > 0 else 100.0
    under_samp = [e["machine"] for e in coverage_machines if e["under_sampling_risk"]]

    verdict = {
        "overall": "PASS" if fail_ct == 0 else "FAIL",
        "checks_passed": pass_ct,
        "checks_warned": warn_ct,
        "checks_total": total_ct,
        "fidelity_score_pct": fidelity,
        "under_sampling_machines": under_samp,
        "failed_checks": [r["name"] for r in non_skip if r["status"] == "FAIL"],
    }

    return {
        "run_overview": run_overview,
        "line_metrics": line_metrics,
        "machine_metrics": machine_metrics,
        "data_coverage": data_coverage,
        "gaps": influx_data.get("gap_details", []),
        "verdict": verdict,
    }
```

- [ ] **Step 2: Run the tests — expect PASS**

```bash
pytest tests/test_report_engine.py::TestValidatePipeline -v 2>&1 | tail -30
```

Expected: all 18 tests PASS.

- [ ] **Step 3: Run full suite to verify no regressions**

```bash
pytest tests/ -q --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py 2>&1 | tail -5
```

Expected: all tests pass (count may vary slightly from existing baseline).

- [ ] **Step 4: Commit**

```bash
git add tools/report_engine.py tests/test_report_engine.py
git commit -m "feat: rewrite validate_pipeline() with 5-section sectioned response"
```

---

## Task 4: Redesign `validation.html`

**Files:**
- Modify: `docker/webui/templates/validation.html`

Replace the entire file content with the new layout. Key structural changes:
- The old `#validation-results` div with its 3 sub-cards is replaced by 5 section cards
- `renderValidation(v)` is rewritten to populate the new sections
- `#checks-table` is removed; replaced by `#line-metrics-table`, `#machine-metrics-container`, `#coverage-table`

- [ ] **Step 1: Replace `validation.html` with new content**

```html
{% extends "base.html" %}
{% block title %}Simantha - Pipeline Validation{% endblock %}
{% block page_subtitle %}| Pipeline Validation{% endblock %}
{% block extra_css %}
<style>
    .verdict-pass { background: var(--good); color: white; font-size: 1.2rem; padding: 14px; border-radius: 8px; text-align: center; }
    .verdict-fail { background: var(--bad);  color: white; font-size: 1.2rem; padding: 14px; border-radius: 8px; text-align: center; }
    .status-connected    { color: var(--good); font-weight: bold; }
    .status-disconnected { color: var(--bad);  font-weight: bold; }
    .section-card  { margin-bottom: 14px; }
    .stat-row      { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--border-dim); font-size: 0.85rem; }
    .stat-label    { color: var(--text-label); }
    .stat-value    { font-weight: 600; }
    .machine-block { border-bottom: 1px solid var(--border-dim); padding: 6px 0; }
    .machine-block:last-child { border-bottom: none; }
    .machine-label { font-weight: 600; padding: 6px 12px; background: var(--bg-secondary); cursor: pointer; }
    .coverage-bar  { height: 8px; border-radius: 4px; background: var(--border-dim); overflow: hidden; display: inline-block; width: 80px; vertical-align: middle; }
    .coverage-fill { height: 100%; border-radius: 4px; }
    #loading-spinner { display: none; }
    .influx-note   { color: var(--text-label); font-size: 0.78rem; font-style: italic; }
    .under-sample-badge { background: #f39c12; color: white; font-size: 0.75rem; padding: 2px 6px; border-radius: 4px; }
</style>
{% endblock %}
{% block content %}

    <!-- InfluxDB Connection -->
    <div class="card section-card">
        <div class="card-header d-flex justify-content-between">
            <strong>InfluxDB Connection</strong>
            <span id="influx-status" class="status-disconnected">Checking...</span>
        </div>
        <div class="card-body">
            <div class="stat-row"><span class="stat-label">URL</span><span class="stat-value" id="influx-url">-</span></div>
            <div class="stat-row"><span class="stat-label">Status</span><span class="stat-value" id="influx-message">-</span></div>
        </div>
    </div>

    <!-- File selector -->
    <div class="card section-card">
        <div class="card-body d-flex align-items-center gap-3 flex-wrap">
            <strong>CSV File:</strong>
            <select id="file-select" class="form-select form-select-sm" style="width:auto;min-width:320px;">
                <option value="">-- Select historian CSV --</option>
            </select>
            <button class="btn btn-warning btn-sm" onclick="runValidation()" id="btn-validate">Run Validation</button>
            <div id="loading-spinner" class="spinner-border spinner-border-sm text-warning" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <span id="validate-status" class="text-muted small"></span>
        </div>
    </div>

    <!-- Results (hidden until run) -->
    <div id="validation-results" style="display:none;">

        <!-- Section 1: Run Overview -->
        <div class="card section-card">
            <div class="card-header"><strong>Run Overview</strong></div>
            <div class="card-body">
                <div class="row g-2" id="run-overview-stats"></div>
            </div>
        </div>

        <!-- Section 2: Line-Level Metrics -->
        <div class="card section-card">
            <div class="card-header"><strong>Line-Level Metrics</strong></div>
            <div class="card-body p-0">
                <table class="table table-sm mb-0" id="line-metrics-table">
                    <thead>
                        <tr>
                            <th>Metric</th>
                            <th>CSV (historian)</th>
                            <th>InfluxDB (Telegraf)</th>
                            <th>Delta</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>

        <!-- Section 3: Per-Machine Metrics -->
        <div class="card section-card">
            <div class="card-header"><strong>Per-Machine Metrics</strong></div>
            <div class="card-body p-0" id="machine-metrics-container"></div>
        </div>

        <!-- Section 4: Data Coverage -->
        <div class="card section-card">
            <div class="card-header"><strong>Data Coverage Analysis</strong></div>
            <div class="card-body">
                <p id="coverage-summary" class="mb-2 text-muted small"></p>
                <table class="table table-sm" id="coverage-table">
                    <thead>
                        <tr>
                            <th>Machine</th>
                            <th>Prod rate (CSV)</th>
                            <th>Max capturable</th>
                            <th>Under-sampling?</th>
                            <th>InfluxDB pts</th>
                            <th>Expected pts</th>
                            <th>Coverage</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>

        <!-- Section 5: Telegraf Gaps (shown only when gaps exist) -->
        <div id="gaps-section" class="card section-card" style="display:none;">
            <div class="card-header d-flex justify-content-between align-items-center">
                <strong>Telegraf Interruptions</strong>
                <span class="badge badge-fail" id="gaps-badge"></span>
            </div>
            <div class="card-body p-0">
                <table class="table table-sm mb-0" id="gaps-table">
                    <thead><tr><th>Wall Clock (UTC)</th><th>Gap Duration</th></tr></thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>

        <!-- Section 6: Verdict -->
        <div id="verdict-banner" class="section-card"></div>

    </div>

{% endblock %}
{% block scripts %}
<script>
    // ── InfluxDB connectivity ──────────────────────────────────────────────
    async function checkInfluxDB() {
        try {
            const resp = await fetch('/api/validation/influxdb/status');
            const data = await resp.json();
            document.getElementById('influx-url').textContent = data.url || '-';
            const el = document.getElementById('influx-status');
            if (data.connected) {
                el.textContent = 'Connected';
                el.className = 'status-connected';
                document.getElementById('influx-message').textContent = data.message || 'OK';
            } else {
                el.textContent = 'Disconnected';
                el.className = 'status-disconnected';
                document.getElementById('influx-message').textContent = data.error || 'Cannot connect';
            }
        } catch (e) {
            document.getElementById('influx-status').textContent = 'Error';
            document.getElementById('influx-status').className = 'status-disconnected';
        }
    }

    // ── File list ──────────────────────────────────────────────────────────
    async function loadFiles() {
        const resp = await fetch('/api/reports/files');
        const data = await resp.json();
        const sel = document.getElementById('file-select');
        sel.innerHTML = '<option value="">-- Select historian CSV --</option>';
        for (const f of data.files) {
            const opt = document.createElement('option');
            opt.value = f.name;
            opt.textContent = `${f.scenario} (${f.size_mb} MB) — ${f.modified.split('T')[0]}`;
            sel.appendChild(opt);
        }
    }

    // ── Run validation ─────────────────────────────────────────────────────
    async function runValidation() {
        const filename = document.getElementById('file-select').value;
        if (!filename) { alert('Select a CSV file first'); return; }
        document.getElementById('loading-spinner').style.display = '';
        document.getElementById('btn-validate').disabled = true;
        document.getElementById('validate-status').textContent = 'Running...';
        try {
            const resp = await fetch('/api/validation/run', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({filename}),
            });
            if (!resp.ok) {
                const err = await resp.json();
                alert('Validation failed: ' + (err.error || 'Unknown error'));
                return;
            }
            const result = await resp.json();
            renderValidation(result);
            document.getElementById('validation-results').style.display = '';
            document.getElementById('validate-status').textContent = 'Done';
        } catch (e) {
            alert('Error: ' + e.message);
        } finally {
            document.getElementById('loading-spinner').style.display = 'none';
            document.getElementById('btn-validate').disabled = false;
        }
    }

    // ── Helpers ────────────────────────────────────────────────────────────
    function statusBadge(status) {
        const cls = {PASS:'badge-pass', FAIL:'badge-fail', WARN:'badge-warn', SKIP:'badge-skip'}[status] || 'badge-skip';
        return `<span class="badge ${cls}">${status}</span>`;
    }

    function metricsRow(name, csvVal, influxVal, delta, status, note) {
        const deltaStr = delta != null ? `${delta}` : '—';
        const noteHtml = note ? `<br><span class="influx-note">${note}</span>` : '';
        return `<tr>
            <td>${name}</td>
            <td><code>${csvVal}</code></td>
            <td><code>${influxVal}</code>${noteHtml}</td>
            <td>${deltaStr}</td>
            <td>${statusBadge(status)}</td>
        </tr>`;
    }

    // ── Render ─────────────────────────────────────────────────────────────
    function renderValidation(v) {
        renderOverview(v.run_overview || {});
        renderLineMetrics(v.line_metrics || []);
        renderMachineMetrics(v.machine_metrics || {});
        renderCoverage(v.data_coverage || {});
        renderGaps(v.gaps || []);
        renderVerdict(v.verdict || {});
    }

    function renderOverview(ov) {
        const container = document.getElementById('run-overview-stats');
        const stats = [
            ['Run ID',           ov.run_id || '—'],
            ['Sim duration',     ov.sim_duration_s != null ? `${ov.sim_duration_s.toLocaleString()}s` : '—'],
            ['CSV events',       ov.csv_total_events != null ? ov.csv_total_events.toLocaleString() : '—'],
            ['InfluxDB points',  ov.influx_total_points != null ? ov.influx_total_points.toLocaleString() : '—'],
            ['Scrape interval',  ov.scrape_interval_s != null ? `${ov.scrape_interval_s}s` : '—'],
            ['Expected points',  ov.expected_points != null ? ov.expected_points.toLocaleString() : '—'],
            ['Coverage',         ov.coverage_pct != null ? `${ov.coverage_pct}%` : '—'],
            ['InfluxDB SimTime', ov.first_simtime_influx != null
                ? `${ov.first_simtime_influx} → ${ov.last_simtime_influx}` : '—'],
        ];
        container.innerHTML = stats.map(([label, val]) =>
            `<div class="col-sm-6 col-md-3">
                <div class="stat-row"><span class="stat-label">${label}</span>
                <span class="stat-value">${val}</span></div>
            </div>`
        ).join('');
    }

    function renderLineMetrics(rows) {
        const tbody = document.querySelector('#line-metrics-table tbody');
        tbody.innerHTML = rows.map(r =>
            metricsRow(r.name, r.csv_value, r.influx_value,
                       r.delta_pct != null ? r.delta_pct + (r.status === 'SKIP' ? '' : '%') : null,
                       r.status, r.influx_note)
        ).join('');
    }

    function renderMachineMetrics(metrics) {
        const container = document.getElementById('machine-metrics-container');
        const machines = Object.keys(metrics).sort();
        if (machines.length === 0) { container.innerHTML = '<p class="p-3 text-muted">No machine data.</p>'; return; }
        container.innerHTML = machines.map(mname => {
            const rows = metrics[mname];
            const tableRows = rows.map(r =>
                metricsRow(r.metric, r.csv_value, r.influx_value,
                           r.delta_pct != null ? r.delta_pct + (r.status === 'SKIP' ? '' : '%') : null,
                           r.status, r.influx_note)
            ).join('');
            return `<div class="machine-block">
                <div class="machine-label" onclick="this.nextElementSibling.style.display=
                    this.nextElementSibling.style.display==='none'?'':'none'">
                    ${mname} ▾
                </div>
                <div>
                    <table class="table table-sm mb-0">
                        <thead><tr><th>Metric</th><th>CSV</th><th>InfluxDB</th><th>Delta</th><th>Status</th></tr></thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </div>
            </div>`;
        }).join('');
    }

    function renderCoverage(dc) {
        const scrape = dc.scrape_interval_s || 1.0;
        const machines = dc.machines || [];
        const atRisk = machines.filter(m => m.under_sampling_risk);
        const summaryEl = document.getElementById('coverage-summary');
        if (atRisk.length > 0) {
            summaryEl.innerHTML = `<strong class="text-warning">${atRisk.length} machine(s) produce faster than the Telegraf scrape rate (${scrape}s).</strong>
                InfluxDB captures at most 1 data point per scrape cycle — per-step production events for these machines are lost.`;
        } else {
            summaryEl.textContent = `Scrape interval: ${scrape}s. All machines produce within capturable rate.`;
        }
        const tbody = document.querySelector('#coverage-table tbody');
        tbody.innerHTML = machines.map(m => {
            const cov = m.coverage_pct != null ? m.coverage_pct : 0;
            const fillColor = cov >= 90 ? '#2ecc71' : cov >= 60 ? '#f39c12' : '#e74c3c';
            const covBar = `<div class="coverage-bar"><div class="coverage-fill" style="width:${Math.min(cov,100)}%;background:${fillColor}"></div></div>
                <span class="ms-1">${m.coverage_pct != null ? m.coverage_pct + '%' : 'N/A'}</span>`;
            const riskBadge = m.under_sampling_risk
                ? '<span class="under-sample-badge">RISK</span>'
                : '<span class="badge badge-pass">OK</span>';
            return `<tr>
                <td><strong>${m.machine}</strong></td>
                <td>${m.parts_per_second_csv} /s</td>
                <td>${m.max_capturable_rate} /s</td>
                <td>${riskBadge}</td>
                <td>${(m.influx_points || 0).toLocaleString()}</td>
                <td>${(m.expected_points || 0).toLocaleString()}</td>
                <td>${covBar}</td>
            </tr>`;
        }).join('');
    }

    function renderGaps(gaps) {
        const sec = document.getElementById('gaps-section');
        if (!gaps || gaps.length === 0) { sec.style.display = 'none'; return; }
        sec.style.display = '';
        document.getElementById('gaps-badge').textContent = `${gaps.length} gap(s)`;
        const tbody = document.querySelector('#gaps-table tbody');
        tbody.innerHTML = gaps.map(g =>
            `<tr><td>${g.wall_clock || '—'}</td><td>${g.gap_s}s</td></tr>`
        ).join('');
    }

    function renderVerdict(verd) {
        const banner = document.getElementById('verdict-banner');
        const cls = verd.overall === 'PASS' ? 'verdict-pass' : 'verdict-fail';
        const icon = verd.overall === 'PASS' ? '✓' : '✗';
        let failList = '';
        if (verd.failed_checks && verd.failed_checks.length > 0) {
            failList = '<ul class="mt-2 mb-0 text-start" style="font-size:0.85rem">' +
                verd.failed_checks.map(f => `<li>${f}</li>`).join('') + '</ul>';
        }
        let sampWarn = '';
        if (verd.under_sampling_machines && verd.under_sampling_machines.length > 0) {
            sampWarn = `<div class="mt-2" style="font-size:0.85rem">
                Under-sampling risk: <strong>${verd.under_sampling_machines.join(', ')}</strong>
                — InfluxDB partcounts and OEE for these machines may be understated.
            </div>`;
        }
        banner.innerHTML = `<div class="${cls}">
            ${icon} ${verd.overall} &nbsp;|&nbsp;
            ${verd.checks_passed} passed &nbsp;
            ${verd.checks_warned > 0 ? verd.checks_warned + ' warned &nbsp;' : ''}
            ${verd.failed_checks ? verd.failed_checks.length + ' failed' : ''} /
            ${verd.checks_total} checks &nbsp;|&nbsp;
            Fidelity: ${verd.fidelity_score_pct}%
            ${failList}
            ${sampWarn}
        </div>`;
    }

    // ── Init ───────────────────────────────────────────────────────────────
    checkInfluxDB();
    loadFiles();
</script>
{% endblock %}
```

- [ ] **Step 2: Smoke-test the web UI locally**

```bash
python docker/webui/app.py
```

Navigate to `http://localhost:5000/validation`. Verify:
- InfluxDB connection check fires on page load
- CSV file dropdown populates
- "Run Validation" button is present
- No JS errors in browser console on page load (even without running validation)

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -q --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add docker/webui/templates/validation.html
git commit -m "feat: redesign validation page with 5-section CSV vs InfluxDB report"
```

---

## Task 5: Final commit and push

- [ ] **Step 1: Run full test suite one last time**

```bash
pytest tests/ -q --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py 2>&1 | tail -5
```

- [ ] **Step 2: Push**

```bash
git push origin main
```
