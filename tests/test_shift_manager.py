"""Shift rotation, metrics, and the cycle_time_factor performance knob.

ShiftManager itself is pure bookkeeping — no engine coupling. cycle_time_factor
is the one field that a caller (run_manager) reads to influence the engine;
ShiftManager never applies it itself.
"""
from simengine.runtime.shift_manager import (
    ShiftDefinition,
    ShiftManager,
    create_shift_manager_from_config,
)


def two_shift_config(night_factor=1.5, day_factor=None):
    night = {"name": "Night Shift", "duration": 2.0, "cycle_time_factor": night_factor}
    day = {"name": "Day Shift", "duration": 100.0}
    if day_factor is not None:
        day["cycle_time_factor"] = day_factor
    return {"shifts": {"schedule": [night, day]}}


class TestCreateShiftManagerFromConfig:
    def test_no_shifts_key_returns_none(self):
        assert create_shift_manager_from_config({}, ["S1"]) is None

    def test_empty_schedule_returns_none(self):
        assert create_shift_manager_from_config(
            {"shifts": {"schedule": []}}, ["S1"]) is None

    def test_builds_definitions_in_order(self):
        mgr = create_shift_manager_from_config(two_shift_config(), ["S1"])
        names = [d.name for d in mgr.shift_definitions]
        assert names == ["Night Shift", "Day Shift"]

    def test_cycle_time_factor_defaults_to_1_0_when_absent(self):
        """A shift that doesn't set cycle_time_factor must not silently
        change simulation behavior — matches nameplate pace exactly."""
        mgr = create_shift_manager_from_config(two_shift_config(), ["S1"])
        day = mgr.shift_definitions[1]
        assert day.cycle_time_factor == 1.0

    def test_cycle_time_factor_parsed_when_present(self):
        mgr = create_shift_manager_from_config(two_shift_config(night_factor=1.25), ["S1"])
        assert mgr.shift_definitions[0].cycle_time_factor == 1.25

    def test_cycle_time_factor_coerced_to_float(self):
        """YAML can hand back an int (e.g. `cycle_time_factor: 1`); the
        multiplication in station.py assumes a float."""
        cfg = {"shifts": {"schedule": [{"name": "S", "duration": 10, "cycle_time_factor": 1}]}}
        mgr = create_shift_manager_from_config(cfg, ["S1"])
        assert mgr.shift_definitions[0].cycle_time_factor == 1.0
        assert isinstance(mgr.shift_definitions[0].cycle_time_factor, float)


class TestGetCurrentCycleTimeFactor:
    def test_returns_first_shift_factor_initially(self):
        mgr = create_shift_manager_from_config(two_shift_config(night_factor=1.5), ["S1"])
        assert mgr.get_current_cycle_time_factor() == 1.5

    def test_reflects_rotation(self):
        """After rotating past Night Shift's duration, the factor must
        switch to the new current shift's value — this is the exact
        accessor run_manager polls once per step."""
        mgr = create_shift_manager_from_config(
            two_shift_config(night_factor=1.5, day_factor=0.9), ["S1"])
        assert mgr.get_current_cycle_time_factor() == 1.5
        rotated = mgr.check_shift_rotation(current_sim_time=2.0)
        assert rotated is True
        assert mgr.get_current_cycle_time_factor() == 0.9

    def test_no_rotation_before_shift_end(self):
        mgr = create_shift_manager_from_config(
            two_shift_config(night_factor=1.5, day_factor=0.9), ["S1"])
        assert mgr.check_shift_rotation(current_sim_time=1.0) is False
        assert mgr.get_current_cycle_time_factor() == 1.5

    def test_default_schedule_is_all_1_0_factor(self):
        """A shift schedule with no cycle_time_factor anywhere reproduces the
        pre-feature behavior exactly: every shift reports 1.0."""
        cfg = {"shifts": {"schedule": [
            {"name": "Day", "duration": 50.0},
            {"name": "Night", "duration": 50.0},
        ]}}
        mgr = create_shift_manager_from_config(cfg, ["S1"])
        assert mgr.get_current_cycle_time_factor() == 1.0
        mgr.check_shift_rotation(current_sim_time=50.0)
        assert mgr.get_current_cycle_time_factor() == 1.0


class TestShiftDefinitionDefaults:
    def test_cycle_time_factor_defaults_to_1_0_for_direct_construction(self):
        """Anything that builds ShiftDefinition directly (not through YAML)
        without knowing about the new field gets nameplate pace."""
        d = ShiftDefinition(name="X", duration=10.0)
        assert d.cycle_time_factor == 1.0


class TestShiftManagerConstruction:
    def test_current_shift_is_first_definition(self):
        defs = [ShiftDefinition(name="A", duration=10.0),
                ShiftDefinition(name="B", duration=10.0)]
        mgr = ShiftManager(defs, ["S1"])
        assert mgr.get_current_shift_info()["shift_name"] == "A"

    def test_rotation_wraps_around(self):
        defs = [ShiftDefinition(name="A", duration=1.0, cycle_time_factor=1.1),
                ShiftDefinition(name="B", duration=1.0, cycle_time_factor=0.9)]
        mgr = ShiftManager(defs, ["S1"])
        mgr.check_shift_rotation(1.0)   # -> B
        assert mgr.get_current_cycle_time_factor() == 0.9
        mgr.check_shift_rotation(2.0)   # -> A again
        assert mgr.get_current_cycle_time_factor() == 1.1
