# Validation Report: CSV vs InfluxDB Side-by-Side Design

## Goal

Replace the current thin 6-check validation page with a comprehensive, sectioned fidelity report that compares every major KPI from the CSV historian against the corresponding InfluxDB (Telegraf) value, surfacing data loss due to OPC UA under-sampling (cycle time < scrape interval), and quantifying per-machine and line-level metric accuracy.

## Background

The existing `/validation` page runs five checks (update rate, final throughput, OEE mean, per-machine partcounts, buffer levels) and produces a single PASS/FAIL verdict. A long run of `full_feature_8_machine_line_rtf` revealed that two machines with sub-1-second cycle times were severely under-represented in InfluxDB — Telegraf's 1-second scrape interval missed most production events, making the InfluxDB partcounts and OEE values for those machines unreliable. The current report did not surface this problem clearly.

## Architecture

Three files change:

| File | Change |
|------|--------|
| `tools/analyze_historian.py` — `query_influxdb_telegraf()` | Add Flux queries for per-machine OEE mean, Availability mean, final DownTime, SPC CumulativeOOC, and per-machine data point counts |
| `tools/report_engine.py` — `validate_pipeline()` | Restructure output from flat `checks[]` to labelled sections; derive all CSV-side metrics; compute delta % and status per metric |
| `docker/webui/templates/validation.html` | Replace single checks table with five rendered sections; update JS to handle new response shape |
| `docker/webui/app.py` | No logic change — `/api/validation/run` passes through response unchanged |

The API response shape changes from `{checks: [...]}` to `{run_overview, line_metrics, machine_metrics, data_coverage, gaps, verdict}`. The only consumer of this endpoint is `validation.html`.

## API Response Shape

```python
{
  "run_overview": {
    "run_id": str,
    "sim_start": float,           # sim_time of first event (CSV)
    "sim_end": float,             # sim_time of last event (CSV)
    "sim_duration_s": float,
    "csv_total_events": int,
    "influx_total_points": int,
    "scrape_interval_s": float,   # derived from Telegraf elapsed intervals
    "expected_points": int,       # floor(sim_duration_s / scrape_interval_s)
    "coverage_pct": float,        # influx_total_points / expected_points * 100
    "first_simtime_influx": float | None,
    "last_simtime_influx": float | None,
  },

  "line_metrics": [               # one dict per metric
    {
      "name": str,                # e.g. "Parts produced"
      "csv_value": str,
      "influx_value": str,        # "N/A" when field absent from OPC UA
      "influx_note": str | None,  # explains N/A if applicable
      "delta_pct": float | None,
      "status": "PASS" | "FAIL" | "WARN" | "SKIP",
    }, ...
  ],

  "machine_metrics": {            # keyed by machine name e.g. "M1"
    "M1": [
      {
        "metric": str,
        "csv_value": str,
        "influx_value": str,
        "influx_note": str | None,
        "delta_pct": float | None,
        "status": "PASS" | "FAIL" | "WARN" | "SKIP",
      }, ...
    ], ...
  },

  "data_coverage": {
    "scrape_interval_s": float,
    "machines": [
      {
        "machine": str,
        "parts_per_second_csv": float,   # csv_partcount / sim_duration_s
        "under_sampling_risk": bool,     # parts_per_second > 1/scrape_interval
        "influx_points": int,
        "expected_points": int,
        "coverage_pct": float,
      }, ...
    ],
  },

  "gaps": [                       # Telegraf gaps > 5s
    {"wall_clock": str, "gap_s": int}, ...
  ],

  "verdict": {
    "overall": "PASS" | "FAIL",
    "checks_passed": int,
    "checks_total": int,
    "fidelity_score_pct": float,  # pct of non-N/A checks that PASS or WARN
    "under_sampling_machines": [str],  # machines flagged for under-sampling
  },
}
```

## Section 1: Run Overview

Displayed as a compact stat row. Fields:

| Stat | Source |
|------|--------|
| Run ID | CSV `run_id` column |
| Sim duration | CSV `sim_time` range |
| CSV total events | `len(df)` |
| InfluxDB total points | `query total_points` |
| Telegraf scrape interval | median of `elapsed` intervals from SimTime query |
| Expected points | `floor(sim_duration / scrape_interval)` |
| Overall coverage % | `total_points / expected_points × 100` |

## Section 2: Line-Level Metrics

Side-by-side table. CSV source is the historian events DataFrame; InfluxDB source is the Telegraf-scraped OPC UA fields.

| Metric | CSV source | InfluxDB field | Pass threshold |
|--------|-----------|----------------|----------------|
| Parts produced | last `partcount` from PRODUCTION_SUMMARY | `Throughput` last | ≤ 2 parts |
| Good parts | PRODUCTION_SUMMARY `extra_json.good_parts` | N/A (historian only) | — |
| Defective parts | PRODUCTION_SUMMARY `extra_json.defective_parts` | N/A (historian only) | — |
| Quality rate | good / (good + defective) | N/A (historian only) | — |
| Total scrap events | count of SCRAP event_type rows | `TotalScrap` last | ≤ 1% diff |
| Total rework events | count of REWORK event_type rows | N/A (historian only) | — |
| Line OEE mean | PRODUCTION_SUMMARY `extra_json.line_oee` mean | `LineOEE` mean | ≤ 0.05 abs |
| Total failures | count of STATE_CHANGE where new_state=FAILED | N/A (complex) | — |
| Total SPC violations | count of SPC_VIOLATION event_type rows | sum of `M{i}_SPC_CumulativeOOC` last values | ≤ 5% diff |
| Total alarms | count of ALARM event_type rows | N/A (not OPC UA field) | — |
| Telegraf update gaps > 5s | 0 (historian is gapless) | `gaps_over_5s` count | ≤ 3 |

## Section 3: Per-Machine Metrics

One collapsible block per machine, each containing a sub-table:

| Metric | CSV source | InfluxDB field | Pass threshold |
|--------|-----------|----------------|----------------|
| Part count | max partcount from STATE_CHANGE or PRODUCTION_SUMMARY extra_json | `M{i}_PartCount` last | ≤ 2% diff |
| OEE mean | mean of `oee` col from STATE_CHANGE rows for this machine | `M{i}_OEE` mean | ≤ 0.05 abs |
| Availability mean | derived from `down_time` / elapsed (STATE_CHANGE) | `M{i}_Availability` mean | ≤ 0.05 abs |
| Total downtime (s) | sum of repair durations from UNDER_REPAIR events | `M{i}_DownTime` last | ≤ 5% diff |
| Failure count | count of STATE_CHANGE where new_state=FAILED | N/A | — |
| MTTR mean (s) | mean repair duration from STATE_CHANGE pairs | N/A (snapshot data unreliable) | — |
| SPC violations | count of SPC_VIOLATION rows for this machine | `M{i}_SPC_CumulativeOOC` last | ≤ 10% diff |
| Alarms | count of ALARM rows for this machine | N/A (not OPC UA field) | — |
| Rework events | count of REWORK rows for this machine | N/A (historian only) | — |
| Scrap events | count of SCRAP rows for this machine | N/A (historian only) | — |

MTTR derivation from CSV: pair consecutive FAILED → PROCESSING (or IDLE) transitions for the same machine and compute the duration between them.

For metrics with N/A on the InfluxDB side, the status column shows `SKIP` and a tooltip explains which OPC UA field is absent or why derivation is not reliable.

## Section 4: Data Coverage Analysis

Table with one row per machine:

| Column | Description |
|--------|-------------|
| Machine | M1 … M8 |
| Production rate (CSV) | `partcount / sim_duration_s` parts/s |
| Scrape interval | median elapsed from InfluxDB |
| Max capturable rate | `1 / scrape_interval_s` parts/s |
| Under-sampling risk | YES / NO badge (risk when production rate > max capturable rate) |
| InfluxDB points | actual count for this machine |
| Expected points | `floor(sim_duration / scrape_interval)` |
| Coverage % | progress bar + number |

Machines flagged with under-sampling risk are highlighted in amber. The section opens with a plain-English summary: *"2 machines produce faster than the Telegraf scrape rate (1.0s). InfluxDB captures at most 1 data point per scrape cycle, so per-step production events for these machines are lost."*

## Section 5: Verdict

- Overall PASS/FAIL badge
- Checks passed / total (excluding N/A)
- Fidelity score % (PASS+WARN checks / non-N/A checks)
- List of machines with under-sampling risk
- List of failed checks

## Thresholds and Status Logic

| Status | Meaning |
|--------|---------|
| PASS | delta ≤ configured threshold |
| WARN | delta > threshold but ≤ 2× threshold |
| FAIL | delta > 2× threshold |
| SKIP | InfluxDB field absent or unreliable (N/A) |

SKIP does not count against PASS/FAIL verdict. Under-sampling risk is reported separately and does not flip the verdict (it is diagnostic, not a hard failure).

## New InfluxDB Queries Required

Added to `query_influxdb_telegraf()`:

1. **Per-machine OEE mean** — `M{i}_OEE` field, `mean()` over time range, for each machine present in CSV
2. **Per-machine Availability mean** — `M{i}_Availability` field, `mean()`
3. **Per-machine DownTime last** — `M{i}_DownTime` field, `last()`
4. **Per-machine SPC CumulativeOOC last** — `M{i}_SPC_CumulativeOOC` field, `last()`
5. **Per-machine point count** — `count()` grouped by field prefix `M{i}_PartCount`, one number per machine
6. **TotalScrap last** — `TotalScrap` field, `last()`
7. **LineOEE mean** — `LineOEE` field, `mean()` (replaces existing timeseries query)

The machine list is inferred from the CSV column headers (machines present in CSV drive which `M{i}` queries are issued), avoiding hardcoded machine counts.

## What Is Not in InfluxDB (N/A fields)

These metrics appear in the report from the CSV side only, with an explanatory note in the InfluxDB column:

- Good parts / defective parts — not separate OPC UA node fields
- Total rework / scrap events — historian event types, not OPC UA variables
- Per-machine alarm counts — not OPC UA-published fields
- Per-machine failure counts — not a published OPC UA counter (state snapshots only)
- MTTR — requires sub-second precision on state transitions; snapshot scraping cannot reconstruct reliably

Surfacing these N/A entries explicitly is intentional: it shows what the OPC UA / Telegraf pipeline cannot validate on its own, complementing rather than duplicating the CSV historian.

## Test Coverage

- Unit tests in `tests/test_report_engine.py`: validate `validate_pipeline()` returns correct section structure for a synthetic DataFrame + influx_data dict; cover N/A handling, delta calculation, status thresholds, and MTTR derivation
- No new InfluxDB integration tests (existing pattern: integration tests excluded from CI)
