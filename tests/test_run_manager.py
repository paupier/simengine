"""RunManager.run_segment — shift cycle_time_factor wiring.

The mechanism itself (LineEngine.step(performance_factor=...) and
ShiftManager.get_current_cycle_time_factor()) is covered independently in
test_station_engine.py and test_shift_manager.py. This file covers only the
glue: run_segment must read the *current* shift's factor and pass it into
engine.step() for the step about to run, every step, with no engine-side
knowledge of "shifts" at all.
"""
from simengine.engine.line import LineEngine
from simengine.publishers import build_publishers
from simengine.runtime.run_manager import RunManager
from simengine.runtime.shift_manager import create_shift_manager_from_config

NO_COMMS = {"opcua": {"enabled": False}}  # avoid spinning up a real OPC UA server


def two_station_config(shifts_schedule=None):
    cfg = {
        "stations": [{"name": "S1", "cycle_time": 1.0},
                    {"name": "S2", "cycle_time": 1.0}],
        "buffers": [{"name": "B1", "capacity": 5}],
        "comms": NO_COMMS,
    }
    if shifts_schedule is not None:
        cfg["shifts"] = {"schedule": shifts_schedule}
    return cfg


def run_and_record_factors(config, max_sim_time, shift_mgr):
    """Runs run_segment to completion, returning the performance_factor
    engine.step() was actually called with on each iteration."""
    engine = LineEngine(config, "test", seed=1, run_id="test")
    publishers = build_publishers(config)
    recorded = []
    real_step = engine.step

    def spy_step(performance_factor=1.0):
        recorded.append(performance_factor)
        real_step(performance_factor=performance_factor)

    engine.step = spy_step

    rm = RunManager()
    rm.engine = engine
    rm.run_segment(engine, publishers, speed_ratio=1e9,
                   shift_mgr=shift_mgr, max_sim_time=max_sim_time)
    return recorded


class TestShiftFactorWiring:
    def test_no_shift_manager_uses_factor_1_0(self):
        config = two_station_config()
        recorded = run_and_record_factors(config, max_sim_time=3.0, shift_mgr=None)
        assert recorded == [1.0, 1.0, 1.0]

    def test_single_shift_factor_applied_every_step(self):
        config = two_station_config([
            {"name": "Night Shift", "duration": 100.0, "cycle_time_factor": 1.5},
        ])
        shift_mgr = create_shift_manager_from_config(config, ["S1", "S2"])
        recorded = run_and_record_factors(config, max_sim_time=3.0, shift_mgr=shift_mgr)
        assert recorded == [1.5, 1.5, 1.5]

    def test_factor_switches_exactly_at_the_shift_boundary(self):
        """sim_step=1.0, Night lasts 2.0s, Day is 0.9x. Rotation is checked
        AFTER each step (RunManager._sync_shift), so the step that crosses
        sim_time from 1.0 -> 2.0 (the boundary) is still governed by Night's
        factor — the one that owned the interval [1.0, 2.0). Only the next
        step, starting at sim_time 2.0, reads Day's factor.
        """
        config = two_station_config([
            {"name": "Night Shift", "duration": 2.0, "cycle_time_factor": 1.5},
            {"name": "Day Shift", "duration": 100.0, "cycle_time_factor": 0.9},
        ])
        shift_mgr = create_shift_manager_from_config(config, ["S1", "S2"])
        recorded = run_and_record_factors(config, max_sim_time=4.0, shift_mgr=shift_mgr)
        assert recorded == [1.5, 1.5, 0.9, 0.9]

    def test_shifts_without_cycle_time_factor_reproduce_1_0(self):
        """A shift schedule that predates this feature (no cycle_time_factor
        anywhere) must not change simulation behavior at all."""
        config = two_station_config([
            {"name": "Day", "duration": 50.0},
            {"name": "Night", "duration": 50.0},
        ])
        shift_mgr = create_shift_manager_from_config(config, ["S1", "S2"])
        recorded = run_and_record_factors(config, max_sim_time=5.0, shift_mgr=shift_mgr)
        assert recorded == [1.0] * 5
