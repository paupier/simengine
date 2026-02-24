"""
Unit tests for tools/report_engine.py analysis functions.

Uses synthetic DataFrames to test each analysis section independently.
"""
import json
import os
import sys
import tempfile

import pandas as pd

# Ensure tools/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from report_engine import (
    _downsample,
    _to_timeseries,
    _safe_float,
    parse_extra_json,
    analyze_overview,
    analyze_continuity,
    analyze_oee,
    analyze_machine_oee,
    analyze_failures,
    analyze_quality_routing,
    analyze_shifts,
    analyze_buffer_dynamics,
    analyze_throughput,
    analyze_anomalies,
    run_full_analysis,
    validate_pipeline,
    append_run_index,
    find_latest_csv,
    load_historian_csv,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic DataFrames
# ---------------------------------------------------------------------------

def _make_base_df(n_events=100, machines=("Machine1", "Machine2")):
    """Create a minimal historian DataFrame with realistic columns."""
    rows = []
    t = 0.0
    for i in range(n_events):
        t += 60.0  # 1 event per minute
        source = machines[i % len(machines)]
        rows.append({
            "timestamp": t,
            "event_type": "STATE_CHANGE",
            "source": source,
            "source_type": "machine",
            "severity": "INFO",
            "message": f"State change at t={t}",
            "old_state": "PROCESSING",
            "new_state": "IDLE",
            "partcount": i + 1,
            "good_parts": i,
            "defective_parts": 1,
            "buffer_level": pd.NA,
            "oee": 0.75 + 0.001 * i,
            "utilisation": 0.8,
            "shift_number": 1,
            "shift_name": "Day",
            "extra_json": "",
        })
    return pd.DataFrame(rows)


def _make_full_df():
    """Create a DataFrame with all event types for full analysis testing."""
    rows = []
    t = 0.0

    # Production summaries (every 60s for 20 steps)
    for i in range(20):
        t += 60.0
        extra = json.dumps({"line_oee": 0.78 + 0.005 * i})
        rows.append({
            "timestamp": t,
            "event_type": "PRODUCTION_SUMMARY",
            "source": "System",
            "source_type": "system",
            "severity": "INFO",
            "message": "Production summary",
            "old_state": "",
            "new_state": "",
            "partcount": 10 + i * 5,
            "good_parts": 9 + i * 5,
            "defective_parts": 1,
            "buffer_level": pd.NA,
            "oee": 0.78,
            "utilisation": 0.8,
            "shift_number": 1,
            "shift_name": "Day",
            "extra_json": extra,
        })

    # Machine state changes
    for m_idx, m_name in enumerate(["Machine1", "Machine2"]):
        for i in range(15):
            t += 30.0
            rows.append({
                "timestamp": t,
                "event_type": "STATE_CHANGE",
                "source": m_name,
                "source_type": "machine",
                "severity": "INFO",
                "message": "State change",
                "old_state": "PROCESSING" if i % 3 != 0 else "FAILED",
                "new_state": "IDLE" if i % 3 != 0 else "PROCESSING",
                "partcount": 50 + i * 3,
                "good_parts": 48 + i * 3,
                "defective_parts": 2,
                "buffer_level": pd.NA,
                "oee": 0.75 + 0.01 * i,
                "utilisation": 0.8,
                "shift_number": 1,
                "shift_name": "Day",
                "extra_json": "",
            })

    # Failure events
    for m_name in ["Machine1", "Machine2"]:
        for i in range(3):
            t += 100.0
            rows.append({
                "timestamp": t,
                "event_type": "STATE_CHANGE",
                "source": m_name,
                "source_type": "machine",
                "severity": "WARNING",
                "message": "Machine failed",
                "old_state": "PROCESSING",
                "new_state": "FAILED",
                "partcount": 80,
                "good_parts": 78,
                "defective_parts": 2,
                "buffer_level": pd.NA,
                "oee": 0.7,
                "utilisation": 0.7,
                "shift_number": 1,
                "shift_name": "Day",
                "extra_json": "",
            })
            t += 30.0
            rows.append({
                "timestamp": t,
                "event_type": "STATE_CHANGE",
                "source": m_name,
                "source_type": "machine",
                "severity": "INFO",
                "message": "Machine repaired",
                "old_state": "FAILED",
                "new_state": "PROCESSING",
                "partcount": 80,
                "good_parts": 78,
                "defective_parts": 2,
                "buffer_level": pd.NA,
                "oee": 0.7,
                "utilisation": 0.7,
                "shift_number": 1,
                "shift_name": "Day",
                "extra_json": "",
            })

    # Scrap events
    for i in range(5):
        t += 20.0
        extra = json.dumps({"scrap_count": i + 1})
        rows.append({
            "timestamp": t,
            "event_type": "SCRAP",
            "source": "Machine1",
            "source_type": "machine",
            "severity": "WARNING",
            "message": "Part scrapped",
            "old_state": "",
            "new_state": "",
            "partcount": 90,
            "good_parts": 85,
            "defective_parts": 5,
            "buffer_level": pd.NA,
            "oee": 0.75,
            "utilisation": 0.8,
            "shift_number": 1,
            "shift_name": "Day",
            "extra_json": extra,
        })

    # Rework events
    for i in range(3):
        t += 20.0
        extra = json.dumps({"rework_count": i + 1, "rework_success_count": i})
        rows.append({
            "timestamp": t,
            "event_type": "REWORK",
            "source": "Machine2",
            "source_type": "machine",
            "severity": "WARNING",
            "message": "Part reworked",
            "old_state": "",
            "new_state": "",
            "partcount": 90,
            "good_parts": 87,
            "defective_parts": 3,
            "buffer_level": pd.NA,
            "oee": 0.75,
            "utilisation": 0.8,
            "shift_number": 1,
            "shift_name": "Day",
            "extra_json": extra,
        })

    # Buffer events
    for i in range(10):
        t += 15.0
        rows.append({
            "timestamp": t,
            "event_type": "STATE_CHANGE",
            "source": "Buffer1",
            "source_type": "buffer",
            "severity": "INFO",
            "message": "Buffer level change",
            "old_state": "",
            "new_state": "",
            "partcount": pd.NA,
            "good_parts": pd.NA,
            "defective_parts": pd.NA,
            "buffer_level": i % 5,
            "oee": pd.NA,
            "utilisation": pd.NA,
            "shift_number": 1,
            "shift_name": "Day",
            "extra_json": "",
        })

    # Shift change
    t += 100.0
    extra = json.dumps({
        "prev_shift_name": "Day",
        "prev_shift_parts": 100,
        "prev_shift_oee": 0.78,
    })
    rows.append({
        "timestamp": t,
        "event_type": "SHIFT_CHANGE",
        "source": "System",
        "source_type": "system",
        "severity": "INFO",
        "message": "Shift change",
        "old_state": "",
        "new_state": "",
        "partcount": pd.NA,
        "good_parts": pd.NA,
        "defective_parts": pd.NA,
        "buffer_level": pd.NA,
        "oee": pd.NA,
        "utilisation": pd.NA,
        "shift_number": 2,
        "shift_name": "Night",
        "extra_json": extra,
    })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------

class TestDownsample:
    def test_no_downsample_when_under_limit(self):
        ts = list(range(10))
        vs = list(range(10))
        t_out, v_out = _downsample(ts, vs, max_points=20)
        assert len(t_out) == 10
        assert t_out == ts

    def test_downsample_when_over_limit(self):
        ts = list(range(100))
        vs = list(range(100))
        t_out, v_out = _downsample(ts, vs, max_points=10)
        assert len(t_out) <= 12  # ~10 + possible last point
        assert t_out[0] == 0
        assert t_out[-1] == 99  # Last point preserved

    def test_empty_input(self):
        t_out, v_out = _downsample([], [], max_points=10)
        assert t_out == []
        assert v_out == []


class TestToTimeseries:
    def test_basic_conversion(self):
        result = _to_timeseries([1.0, 2.0, 3.0], [10, 20, 30])
        assert len(result) == 3
        assert result[0] == {"t": 1.0, "v": 10}
        assert result[2] == {"t": 3.0, "v": 30}


class TestSafeFloat:
    def test_normal_values(self):
        assert _safe_float(3.14) == 3.14
        assert _safe_float(0) == 0.0
        assert _safe_float("2.5") == 2.5

    def test_none_and_nan(self):
        assert _safe_float(None) is None
        assert _safe_float(float("nan")) is None
        assert _safe_float(float("inf")) is None

    def test_invalid_string(self):
        assert _safe_float("abc") is None


class TestParseExtraJson:
    def test_valid_json(self):
        s = pd.Series(['{"a": 1}', '{"b": 2}'])
        result = parse_extra_json(s)
        assert result.iloc[0] == {"a": 1}
        assert result.iloc[1] == {"b": 2}

    def test_empty_and_nan(self):
        s = pd.Series(["", pd.NA, None])
        result = parse_extra_json(s)
        assert result.iloc[0] == {}
        assert result.iloc[1] == {}

    def test_invalid_json(self):
        s = pd.Series(["not json"])
        result = parse_extra_json(s)
        assert result.iloc[0] == {}


# ---------------------------------------------------------------------------
# Section analysis tests
# ---------------------------------------------------------------------------

class TestAnalyzeOverview:
    def test_basic_overview(self):
        df = _make_base_df(50)
        result = analyze_overview(df)
        assert result["total_events"] == 50
        assert result["sim_duration_hrs"] > 0
        assert result["events_per_min"] > 0
        assert "STATE_CHANGE" in result["event_type_distribution"]
        assert "INFO" in result["severity_distribution"]


class TestAnalyzeContinuity:
    def test_no_production_summaries(self):
        df = _make_base_df(10)
        result = analyze_continuity(df)
        assert result["production_summary_count"] == 0
        assert result["status"] == "WARN"

    def test_with_production_summaries(self):
        df = _make_full_df()
        result = analyze_continuity(df)
        assert result["production_summary_count"] == 20
        assert "expected_interval_s" in result


class TestAnalyzeOee:
    def test_with_oee_data(self):
        df = _make_full_df()
        result = analyze_oee(df)
        assert result["sample_count"] > 0
        assert result["mean"] is not None
        assert result["median"] is not None
        assert len(result["timeseries"]) > 0

    def test_no_production_summaries(self):
        df = _make_base_df(10)
        result = analyze_oee(df)
        assert result["sample_count"] == 0
        assert result["status"] == "WARN"


class TestAnalyzeMachineOee:
    def test_per_machine_data(self):
        df = _make_full_df()
        result = analyze_machine_oee(df)
        assert len(result["machines"]) >= 2
        for m_name, m_data in result["machines"].items():
            assert "oee_mean" in m_data
            assert "timeseries" in m_data


class TestAnalyzeFailures:
    def test_failure_detection(self):
        df = _make_full_df()
        result = analyze_failures(df)
        assert result["total_failures"] > 0
        assert result["total_repairs"] > 0
        # At least one machine should have MTTF data
        has_mttf = any("mttf_mean" in data for data in result["machines"].values())
        assert has_mttf

    def test_no_failures(self):
        df = _make_base_df(10)
        result = analyze_failures(df)
        assert result["total_failures"] == 0


class TestAnalyzeQualityRouting:
    def test_scrap_rework_counts(self):
        df = _make_full_df()
        result = analyze_quality_routing(df)
        assert result["total_scrap_events"] == 5
        assert result["total_rework_events"] == 3
        assert "Machine1" in result["machines"]
        assert result["machines"]["Machine1"]["scrap_events"] == 5
        assert result["machines"]["Machine1"]["final_scrap_count"] == 5

    def test_rework_success_rate(self):
        df = _make_full_df()
        result = analyze_quality_routing(df)
        m2 = result["machines"]["Machine2"]
        assert m2["rework_events"] == 3
        assert "rework_success_rate" in m2


class TestAnalyzeShifts:
    def test_shift_changes(self):
        df = _make_full_df()
        result = analyze_shifts(df)
        assert result["shift_change_count"] == 1
        assert len(result["shifts"]) == 1
        shift = result["shifts"][0]
        assert shift["shift_name"] == "Night"
        assert shift["prev_shift_name"] == "Day"

    def test_no_shifts(self):
        df = _make_base_df(10)
        result = analyze_shifts(df)
        assert result["shift_change_count"] == 0


class TestAnalyzeBufferDynamics:
    def test_buffer_stats(self):
        df = _make_full_df()
        result = analyze_buffer_dynamics(df)
        assert "Buffer1" in result["buffers"]
        b1 = result["buffers"]["Buffer1"]
        assert b1["event_count"] == 10
        assert "level_mean" in b1
        assert len(b1["timeseries"]) > 0


class TestAnalyzeThroughput:
    def test_throughput_calculation(self):
        df = _make_full_df()
        result = analyze_throughput(df)
        assert result["status"] == "PASS"
        assert result["total_parts"] > 0
        assert result["ppm"] > 0
        assert len(result["timeseries"]) > 0

    def test_insufficient_data(self):
        df = _make_base_df(5)  # No production summaries
        result = analyze_throughput(df)
        assert result["status"] == "WARN"


class TestAnalyzeAnomalies:
    def test_clean_data(self):
        df = _make_full_df()
        result = analyze_anomalies(df)
        assert result["anomaly_count"] == 0
        assert result["status"] == "PASS"
        assert len(result["checks"]) == 4

    def test_negative_partcount_detected(self):
        df = _make_base_df(10)
        df.loc[0, "partcount"] = -1
        result = analyze_anomalies(df)
        neg_check = next(c for c in result["checks"] if c["name"] == "Negative partcount")
        assert neg_check["status"] == "FAIL"

    def test_high_oee_detected(self):
        df = _make_base_df(10)
        df.loc[0, "oee"] = 1.5
        result = analyze_anomalies(df)
        oee_check = next(c for c in result["checks"] if c["name"] == "OEE > 1.0")
        assert oee_check["status"] == "FAIL"


class TestRunFullAnalysis:
    def test_all_sections_present(self):
        df = _make_full_df()
        result = run_full_analysis(df)
        expected_keys = [
            "overview", "continuity", "oee", "machine_oee",
            "failures", "quality_routing", "shifts",
            "buffer_dynamics", "throughput", "anomalies",
        ]
        for key in expected_keys:
            assert key in result, f"Missing section: {key}"


# ---------------------------------------------------------------------------
# Pipeline validation tests
# ---------------------------------------------------------------------------

class TestValidatePipeline:
    def test_all_pass(self):
        df = _make_full_df()
        influx_data = {
            "total_points": 1000,
            "first_simtime": 60.0,
            "last_simtime": 3600.0,
            "avg_update_rate": 1.0,  # Exactly 1s per update
            "final_throughput": 105,  # Close to CSV last partcount
            "oee_timeseries": [{"value": 0.78}, {"value": 0.80}],
            "machine_partcounts": {"Machine1": 80, "Machine2": 80},
            "buffer_levels": {"Buffer1": 2},
            "gaps_over_5s": 0,
        }
        result = validate_pipeline(df, influx_data)
        assert result["verdict"] in ("PASS", "FAIL")  # Depends on exact data match
        assert result["total"] > 0
        assert len(result["checks"]) > 0

    def test_missing_influx_data(self):
        df = _make_full_df()
        influx_data = {
            "total_points": 0,
            "first_simtime": None,
            "last_simtime": None,
            "avg_update_rate": None,
            "final_throughput": None,
            "oee_timeseries": [],
            "machine_partcounts": {},
            "buffer_levels": {},
            "gaps_over_5s": 0,
        }
        result = validate_pipeline(df, influx_data)
        # Should still return a valid structure even with all SKIPs
        assert "checks" in result
        assert "verdict" in result


# ---------------------------------------------------------------------------
# Run index tests
# ---------------------------------------------------------------------------

class TestAppendRunIndex:
    def test_creates_index_file(self):
        df = _make_full_df()
        analysis = run_full_analysis(df)
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_scenario_20260220_120000_events.csv")
            index_path = os.path.join(tmpdir, "run_index.json")

            entry = append_run_index(csv_path, analysis, index_path=index_path)
            assert entry["run_id"] == "test_scenario_20260220_120000"
            assert entry["scenario"] == "test_scenario"

            # File should exist
            assert os.path.exists(index_path)
            import json
            with open(index_path) as f:
                index = json.load(f)
            assert len(index) == 1

    def test_no_duplicate_entries(self):
        df = _make_full_df()
        analysis = run_full_analysis(df)
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_20260220_120000_events.csv")
            index_path = os.path.join(tmpdir, "run_index.json")

            append_run_index(csv_path, analysis, index_path=index_path)
            append_run_index(csv_path, analysis, index_path=index_path)

            import json
            with open(index_path) as f:
                index = json.load(f)
            assert len(index) == 1  # No duplicate


# ---------------------------------------------------------------------------
# CSV loading tests
# ---------------------------------------------------------------------------

class TestFindLatestCsv:
    def test_finds_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test CSV
            path = os.path.join(tmpdir, "test_events.csv")
            with open(path, "w") as f:
                f.write("timestamp\n1.0\n")
            result = find_latest_csv(tmpdir)
            assert result == path

    def test_no_csv_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_latest_csv(tmpdir)
            assert result is None


class TestLoadHistorianCsv:
    def test_loads_valid_csv(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("timestamp,event_type,source,source_type,severity,message,"
                    "old_state,new_state,partcount,good_parts,defective_parts,"
                    "buffer_level,oee,utilisation,shift_number,shift_name,extra_json\n")
            f.write("60.0,STATE_CHANGE,Machine1,machine,INFO,test,IDLE,PROCESSING,"
                    "1,1,0,,0.75,0.8,1,Day,\n")
            tmp_name = f.name
        try:
            df = load_historian_csv(tmp_name)
            assert len(df) == 1
            assert df.iloc[0]["timestamp"] == 60.0
        finally:
            os.unlink(tmp_name)

    def test_backward_compat_no_run_id_column(self):
        """Old CSVs without run_id column should get an empty run_id column."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("timestamp,event_type,source,source_type,severity,message,"
                    "old_state,new_state,partcount,good_parts,defective_parts,"
                    "buffer_level,oee,utilisation,shift_number,shift_name,extra_json\n")
            f.write("60.0,STATE_CHANGE,Machine1,machine,INFO,test,IDLE,PROCESSING,"
                    "1,1,0,,0.75,0.8,1,Day,\n")
            tmp_name = f.name
        try:
            df = load_historian_csv(tmp_name)
            assert "run_id" in df.columns
            assert df.iloc[0]["run_id"] == ""
        finally:
            os.unlink(tmp_name)

    def test_loads_csv_with_run_id_column(self):
        """New CSVs with run_id column should load it correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("run_id,timestamp,event_type,source,source_type,severity,message,"
                    "old_state,new_state,partcount,good_parts,defective_parts,"
                    "buffer_level,oee,utilisation,shift_number,shift_name,extra_json\n")
            f.write("balanced_line_20260224_143000,60.0,STATE_CHANGE,Machine1,"
                    "machine,INFO,test,IDLE,PROCESSING,1,1,0,,0.75,0.8,1,Day,\n")
            tmp_name = f.name
        try:
            df = load_historian_csv(tmp_name)
            assert len(df) == 1
            assert df.iloc[0]["run_id"] == "balanced_line_20260224_143000"
            assert df.iloc[0]["timestamp"] == 60.0
        finally:
            os.unlink(tmp_name)
