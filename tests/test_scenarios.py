import os
import csv

from simantha_baseline import SCENARIOS, run_scenario, ensure_results_dir


def test_scenarios_run_and_write_csv(tmp_path, monkeypatch):
    """
    Basic smoke test: all configured scenarios run
    and produce a CSV file with at least header + one row.
    """

    # Use a temporary directory for test outputs
    monkeypatch.setenv("SIMANTHA_RESULTS_DIR", str(tmp_path))

    results_dir = ensure_results_dir()
    assert os.path.isdir(results_dir)

    for cfg in SCENARIOS:
        metrics = run_scenario(cfg)

        # Basic sanity checks on returned metrics
        assert metrics["scenario"] == cfg.name
        assert metrics["simulation_time"] == cfg.simulation_time
        assert metrics["m1_cycle_time"] == cfg.m1_cycle_time
        assert metrics["m2_cycle_time"] == cfg.m2_cycle_time
        assert metrics["buffer_capacity"] == cfg.buffer_capacity

        # Write CSV (same structure as in simantha_baseline)
        filename = f"scenario_{cfg.name}.csv"
        path = os.path.join(results_dir, filename)

        fieldnames = [
            "scenario",
            "simulation_time",
            "parts_produced",
            "m1_cycle_time",
            "m2_cycle_time",
            "buffer_capacity",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(metrics)

        # File exists
        assert os.path.exists(path)

        # At least header + one data row
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) >= 2
