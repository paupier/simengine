"""RunManager.run_segment — shift cycle_time_factor / health_degrade_factor wiring.

The mechanisms themselves (LineEngine.step(performance_factor=...,
health_degrade_factor=...) and ShiftManager.get_current_cycle_time_factor()/
get_current_health_degrade_factor()) are covered independently in
test_station_engine.py and test_shift_manager.py. This file covers only the
glue: run_segment must read the *current* shift's factors and pass them into
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
    """Runs run_segment to completion, returning a list of
    (performance_factor, health_degrade_factor) engine.step() was actually
    called with on each iteration."""
    engine = LineEngine(config, "test", seed=1, run_id="test")
    publishers = build_publishers(config)
    recorded = []
    real_step = engine.step

    def spy_step(performance_factor=1.0, health_degrade_factor=1.0):
        recorded.append((performance_factor, health_degrade_factor))
        real_step(performance_factor=performance_factor,
                 health_degrade_factor=health_degrade_factor)

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
        assert recorded == [(1.0, 1.0)] * 3

    def test_single_shift_factor_applied_every_step(self):
        config = two_station_config([
            {"name": "Night Shift", "duration": 100.0, "cycle_time_factor": 1.5,
             "health_degrade_factor": 1.3},
        ])
        shift_mgr = create_shift_manager_from_config(config, ["S1", "S2"])
        recorded = run_and_record_factors(config, max_sim_time=3.0, shift_mgr=shift_mgr)
        assert recorded == [(1.5, 1.3)] * 3

    def test_factor_switches_exactly_at_the_shift_boundary(self):
        """sim_step=1.0, Night lasts 2.0s (1.5x cycle time, 1.3x degrade),
        Day is 0.9x/0.8x. Rotation is checked AFTER each step
        (RunManager._sync_shift), so the step that crosses sim_time from
        1.0 -> 2.0 (the boundary) is still governed by Night's factors — the
        ones that owned the interval [1.0, 2.0). Only the next step, starting
        at sim_time 2.0, reads Day's factors.
        """
        config = two_station_config([
            {"name": "Night Shift", "duration": 2.0, "cycle_time_factor": 1.5,
             "health_degrade_factor": 1.3},
            {"name": "Day Shift", "duration": 100.0, "cycle_time_factor": 0.9,
             "health_degrade_factor": 0.8},
        ])
        shift_mgr = create_shift_manager_from_config(config, ["S1", "S2"])
        recorded = run_and_record_factors(config, max_sim_time=4.0, shift_mgr=shift_mgr)
        assert recorded == [(1.5, 1.3), (1.5, 1.3), (0.9, 0.8), (0.9, 0.8)]

    def test_shifts_without_factors_reproduce_1_0(self):
        """A shift schedule that predates this feature (no cycle_time_factor
        or health_degrade_factor anywhere) must not change simulation
        behavior at all."""
        config = two_station_config([
            {"name": "Day", "duration": 50.0},
            {"name": "Night", "duration": 50.0},
        ])
        shift_mgr = create_shift_manager_from_config(config, ["S1", "S2"])
        recorded = run_and_record_factors(config, max_sim_time=5.0, shift_mgr=shift_mgr)
        assert recorded == [(1.0, 1.0)] * 5

    def test_health_degrade_factor_independent_of_cycle_time_factor(self):
        """The two factors are set independently per shift — a shift can
        slow cycle time without touching degradation, or vice versa."""
        config = two_station_config([
            {"name": "Careful Shift", "duration": 100.0,
             "health_degrade_factor": 0.5},  # cycle_time_factor omitted -> 1.0
        ])
        shift_mgr = create_shift_manager_from_config(config, ["S1", "S2"])
        recorded = run_and_record_factors(config, max_sim_time=2.0, shift_mgr=shift_mgr)
        assert recorded == [(1.0, 0.5)] * 2


class TestConfigExposure:
    def test_config_is_none_before_any_run(self):
        rm = RunManager()
        assert rm.config is None

    def test_config_set_on_start_and_survives_stop(self):
        import time
        rm = RunManager()
        rm.start(scenario="balanced_line", seed=1)
        time.sleep(0.2)
        assert rm.config is not None
        assert rm.config["stations"][0]["name"]  # real validated config, not a stub
        rm.stop()
        assert rm.config is not None  # survives stop, like self.scenario does


class TestRecordMetricsWiring:
    def test_record_metrics_called_each_step(self):
        from unittest.mock import MagicMock
        from simengine.events import EventHistorian
        from simengine.events.collect import SnapshotEventCollector

        config = two_station_config()
        engine = LineEngine(config, "wiring_test", seed=1, run_id="run_w")
        publishers = build_publishers(config)
        historian = MagicMock(spec=EventHistorian)
        collector = SnapshotEventCollector()

        rm = RunManager()
        rm.engine = engine
        rm.run_segment(engine, publishers, speed_ratio=1e9,
                        max_sim_time=3.0, historian=historian, collector=collector)

        assert historian.record_metrics.call_count > 0
        # called with the LineSnapshot, not the collected events
        called_arg = historian.record_metrics.call_args_list[0][0][0]
        assert hasattr(called_arg, "sim_time")

    def test_record_metrics_not_called_without_historian(self):
        config = two_station_config()
        engine = LineEngine(config, "wiring_test2", seed=1, run_id="run_w2")
        publishers = build_publishers(config)

        rm = RunManager()
        rm.engine = engine
        # Must not raise even though historian/collector default to None.
        rm.run_segment(engine, publishers, speed_ratio=1e9, max_sim_time=3.0)
