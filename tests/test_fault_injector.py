"""
Tests for fault injection config validation, FaultInjector, and GroundTruthWriter.
"""
import os
import csv
import tempfile

import pytest
from config_loader import validate_fault_injection


# ---------------------------------------------------------------------------
# Task 2: Config validation tests
# ---------------------------------------------------------------------------

def test_empty_fault_injection_is_valid():
    validate_fault_injection({})  # no fault_injection key → no error


def test_valid_health_delta_injection():
    cfg = {"fault_injection": {
        "spc_noise_scale": 2.0,
        "injections": [
            {"type": "health_delta", "machine": "M1",
             "at_sim_time": 1500, "health_delta": 2}
        ]
    }}
    validate_fault_injection(cfg)  # must not raise


def test_valid_noise_ramp_injection():
    cfg = {"fault_injection": {"spc_noise_scale": 1.0, "injections": [
        {"type": "noise_ramp", "machine": "M2", "at_sim_time": 2000,
         "duration": 200, "target_multiplier": 2.5}
    ]}}
    validate_fault_injection(cfg)


def test_valid_cycle_time_offset_injection():
    cfg = {"fault_injection": {"injections": [
        {"type": "cycle_time_offset", "machine": "M4",
         "at_sim_time": 3000, "offset": 0.3}
    ]}}
    validate_fault_injection(cfg)


def test_unknown_injection_type_raises():
    cfg = {"fault_injection": {"injections": [
        {"type": "teleport", "machine": "M1", "at_sim_time": 100}
    ]}}
    with pytest.raises(ValueError, match="Unknown injection type"):
        validate_fault_injection(cfg)


def test_health_delta_missing_machine_raises():
    cfg = {"fault_injection": {"injections": [
        {"type": "health_delta", "at_sim_time": 100, "health_delta": 1}
    ]}}
    with pytest.raises(ValueError, match="machine"):
        validate_fault_injection(cfg)


def test_noise_ramp_missing_duration_raises():
    cfg = {"fault_injection": {"injections": [
        {"type": "noise_ramp", "machine": "M1", "at_sim_time": 100,
         "target_multiplier": 2.0}
    ]}}
    with pytest.raises(ValueError, match="duration"):
        validate_fault_injection(cfg)


def test_spc_noise_scale_negative_raises():
    cfg = {"fault_injection": {"spc_noise_scale": -1.0, "injections": []}}
    with pytest.raises(ValueError, match="spc_noise_scale"):
        validate_fault_injection(cfg)


# ---------------------------------------------------------------------------
# Task 3: FaultInjector unit tests
# ---------------------------------------------------------------------------

from fault_injector import FaultInjector, GroundTruthWriter  # noqa: E402


# --- FaultInjector: health_delta ---

def test_health_delta_fires_at_correct_time():
    injector = FaultInjector([
        {"type": "health_delta", "machine": "M1", "at_sim_time": 500, "health_delta": 2}
    ])
    machine_health = {"M1": 0}
    machine_metrics = {"M1": {"h_max": 4}}
    # Before injection time — no change
    injector.step(499.0, machine_health, machine_metrics)
    assert machine_health["M1"] == 0
    # At injection time — fires
    fired = injector.step(500.0, machine_health, machine_metrics)
    assert machine_health["M1"] == 2
    assert len(fired) == 1
    assert fired[0]["type"] == "health_delta"


def test_health_delta_clamped_to_h_max():
    injector = FaultInjector([
        {"type": "health_delta", "machine": "M1", "at_sim_time": 100, "health_delta": 10}
    ])
    machine_health = {"M1": 2}
    machine_metrics = {"M1": {"h_max": 4}}
    injector.step(100.0, machine_health, machine_metrics)
    assert machine_health["M1"] == 4  # clamped


def test_health_delta_fires_only_once():
    injector = FaultInjector([
        {"type": "health_delta", "machine": "M1", "at_sim_time": 100, "health_delta": 1}
    ])
    machine_health = {"M1": 0}
    machine_metrics = {"M1": {"h_max": 4}}
    injector.step(100.0, machine_health, machine_metrics)
    machine_health["M1"] = 0  # reset externally
    fired = injector.step(101.0, machine_health, machine_metrics)
    assert len(fired) == 0  # does not re-fire


# --- FaultInjector: noise_ramp ---

def test_noise_ramp_starts_at_injection_time():
    injector = FaultInjector([
        {"type": "noise_ramp", "machine": "M2", "at_sim_time": 200,
         "duration": 100, "target_multiplier": 3.0}
    ])
    metrics = {"M2": {"spc_measurement_noise": 0.02, "h_max": 4}}
    # Before ramp
    injector.step(199.0, {}, metrics)
    assert metrics["M2"]["spc_measurement_noise"] == 0.02
    # At start of ramp (progress=0, noise unchanged)
    injector.step(200.0, {}, metrics)
    assert metrics["M2"]["spc_measurement_noise"] == pytest.approx(0.02, abs=1e-6)
    # Midpoint (progress=0.5, noise = 0.02 * (1 + 0.5*(3-1)) = 0.04)
    injector.step(250.0, {}, metrics)
    assert metrics["M2"]["spc_measurement_noise"] == pytest.approx(0.04, abs=1e-4)
    # At end (progress=1.0, noise = 0.02 * 3.0 = 0.06)
    injector.step(300.0, {}, metrics)
    assert metrics["M2"]["spc_measurement_noise"] == pytest.approx(0.06, abs=1e-4)


# --- FaultInjector: cycle_time_offset ---

def test_cycle_time_offset_sets_spc_target():
    injector = FaultInjector([
        {"type": "cycle_time_offset", "machine": "M4", "at_sim_time": 1000, "offset": 0.3}
    ])
    metrics = {"M4": {"cycle_time": 1.1, "h_max": 5}}
    injector.step(1000.0, {}, metrics)
    assert metrics["M4"].get("spc_target_cycle_time") == pytest.approx(1.4, abs=1e-6)


def test_cycle_time_offset_does_not_change_actual_cycle_time():
    injector = FaultInjector([
        {"type": "cycle_time_offset", "machine": "M4", "at_sim_time": 100, "offset": 0.3}
    ])
    metrics = {"M4": {"cycle_time": 1.1, "h_max": 5}}
    injector.step(100.0, {}, metrics)
    assert metrics["M4"]["cycle_time"] == pytest.approx(1.1, abs=1e-6)  # unchanged


# --- GroundTruthWriter ---

def test_ground_truth_writer_creates_csv():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ground_truth.csv")
        writer = GroundTruthWriter(path, run_id="test_run")
        writer.record_injection({
            "type": "health_delta", "machine": "M1",
            "injection_sim_time": 500.0, "health_before": 0, "health_after": 2,
            "h_max": 4,
        })
        writer.close()
        with open(path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["machine"] == "M1"
        assert rows[0]["injection_sim_time"] == "500.0"


def test_ground_truth_writer_updates_failure_time():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ground_truth.csv")
        writer = GroundTruthWriter(path, run_id="test_run")
        writer.record_injection({
            "type": "health_delta", "machine": "M1",
            "injection_sim_time": 500.0, "health_before": 0, "health_after": 2,
            "h_max": 4,
        })
        writer.notify_failure("M1", sim_time=650.0)
        writer.notify_repair_complete("M1", sim_time=670.0)
        writer.close()
        with open(path) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["failure_sim_time"] == "650.0"
        assert rows[0]["repair_complete_sim_time"] == "670.0"
