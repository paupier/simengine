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
