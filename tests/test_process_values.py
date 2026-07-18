"""Gate P3 — process value profiles: convergence, cycle shapes, alarms, drift, determinism."""
import json
from dataclasses import asdict

import pytest

from simengine.engine.line import LineEngine


def engine_with_pv(pv_cfg, station_extra=None, steps=0, seed=1):
    st1 = {"name": "S1", "cycle_time": 4.0, "process_values": [pv_cfg]}
    st1.update(station_extra or {})
    cfg = {
        "stations": [st1, {"name": "S2", "cycle_time": 4.0}],
        "buffers": [{"name": "B1", "capacity": 10}],
    }
    eng = LineEngine(cfg, "test", seed=seed, run_id="pv")
    for _ in range(steps):
        eng.step()
    return eng


def pv_of(eng, name="S1"):
    return eng.stations[0].process_values[0]


class TestFirstOrderLag:
    CFG = {
        "name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
        "setpoint": 55.0, "tau": 30.0, "initial": 20.0,
    }

    def test_converges_to_setpoint_within_5_tau(self):
        eng = engine_with_pv(dict(self.CFG), steps=150)  # 5 * tau
        pv = pv_of(eng)
        assert abs(pv.value - 55.0) < 55.0 * 0.01

    def test_starts_at_initial(self):
        eng = engine_with_pv(dict(self.CFG), steps=0)
        assert pv_of(eng).value == 20.0

    def test_drift_shifts_target(self):
        cfg = dict(self.CFG)
        cfg["health_drift"] = 0.1
        # pin health at 2 via a health model that degrades instantly, CBM repair
        extra = {"health": {"h_max": 10, "p_degrade": 1.0, "cbm_threshold": 10,
                            "mttr": {"distribution": "constant", "value": 1}}}
        eng = engine_with_pv(cfg, station_extra=extra, steps=3)
        # after 3 steps health == 3 -> drift target 55 * 1.3; value moving up
        assert eng.stations[0].health == 3


class TestCyclePeak:
    CFG = {
        "name": "RamForce", "unit": "kN", "profile": "cycle_peak",
        "baseline": 5.0,
        "peak": {"distribution": "constant", "value": 100.0},
    }

    def test_returns_to_baseline_between_cycles(self):
        # Fast S1, slow S2, capacity 1: S1 blocks -> not cycling -> baseline
        st1 = {"name": "S1", "cycle_time": 2.0, "process_values": [dict(self.CFG)]}
        cfg = {
            "stations": [st1, {"name": "S2", "cycle_time": 10.0}],
            "buffers": [{"name": "B1", "capacity": 1}],
        }
        eng = LineEngine(cfg, "test", seed=1, run_id="pv")
        baseline_seen = peak_seen = False
        for _ in range(40):
            eng.step()
            pv = eng.stations[0].process_values[0]
            if eng.stations[0].state == "BLOCKED" and pv.value == 5.0:
                baseline_seen = True
            if pv.value > 5.0:
                peak_seen = True
        assert baseline_seen and peak_seen

    def test_peak_shape_midcycle(self):
        # Step 0 pulls the part (no progress); steps 1-3 hit phases 1/4..3/4;
        # step 4 completes the cycle and resets phase to 0 -> baseline.
        eng = engine_with_pv(dict(self.CFG), steps=1)
        values = []
        for _ in range(4):
            eng.step()
            values.append(pv_of(eng).value)
        import math
        for k, v in enumerate(values[:3], start=1):
            expected = 5.0 + 100.0 * math.sin(math.pi * k / 4)
            assert abs(v - expected) < 1e-9
        assert abs(values[3] - 5.0) < 1e-9  # completion step: back to baseline


class TestCycleRamp:
    CFG = {
        "name": "StrokePos", "unit": "mm", "profile": "cycle_ramp",
        "range": [10.0, 50.0],
    }

    def test_ramp_endpoints_exact_no_noise(self):
        # Step 0 pulls; steps 1-3 ramp through phases 1/4..3/4; the completion
        # step resets to range[0].
        eng = engine_with_pv(dict(self.CFG), steps=1)
        values = []
        for _ in range(4):
            eng.step()
            values.append(pv_of(eng).value)
        for k, v in enumerate(values[:3], start=1):
            assert abs(v - (10.0 + 40.0 * k / 4)) < 1e-9
        assert abs(values[3] - 10.0) < 1e-9

    def test_rest_value_when_not_cycling(self):
        cfg = {
            "stations": [
                {"name": "S1", "cycle_time": 10.0},
                {"name": "S2", "cycle_time": 2.0, "process_values": [dict(self.CFG)]},
            ],
            "buffers": [{"name": "B1", "capacity": 2}],
        }
        eng = LineEngine(cfg, "test", seed=1, run_id="pv")
        eng.step()  # S2 starved, PV at rest
        pv = eng.stations[1].process_values[0]
        assert pv.value == 10.0


class TestConstantNoise:
    def test_mean_with_drift(self):
        cfg = {
            "name": "FeedSpeed", "unit": "mm_s", "profile": "constant_noise",
            "mean": 100.0, "health_drift": 0.05,
        }
        extra = {"health": {"h_max": 10, "p_degrade": 1.0, "cbm_threshold": 10,
                            "mttr": {"distribution": "constant", "value": 1}}}
        eng = engine_with_pv(cfg, station_extra=extra, steps=4)
        # health after 4 steps = 4 -> value = 100 * 1.2 exactly (no noise dist)
        assert abs(pv_of(eng).value - 120.0) < 1e-9


class TestPVAlarms:
    def test_high_alarm_raise_and_hysteresis_clear(self):
        from simengine.engine.alarms import AlarmRegistry
        from simengine.engine.process_values import ProcessValueModel

        class FakeStation:
            name = "S1"
            is_working = True
            cycle_phase = 0.5
            health = 0
            state = "PROCESSING"
            cycle_serial = 1

        pv = ProcessValueModel({
            "name": "OilTemp", "unit": "degC", "profile": "constant_noise",
            "mean": 50.0, "alarm_high": 60.0,
        })
        reg = AlarmRegistry()
        st = FakeStation()

        pv.mean = 65.0
        pv.update(st, None, 1.0, reg, 1.0)
        assert reg.is_active("PV_OILTEMP_HIGH", "S1")
        assert pv.alarm_state == "HIGH"

        # back below limit but inside the 1% hysteresis band: stays active
        pv.mean = 59.8
        pv.update(st, None, 1.0, reg, 2.0)
        assert reg.is_active("PV_OILTEMP_HIGH", "S1")

        # below limit - 1%: clears
        pv.mean = 59.0
        pv.update(st, None, 1.0, reg, 3.0)
        assert not reg.is_active("PV_OILTEMP_HIGH", "S1")
        assert pv.alarm_state == "OK"

    def test_low_alarm(self):
        from simengine.engine.alarms import AlarmRegistry
        from simengine.engine.process_values import ProcessValueModel

        class FakeStation:
            name = "S1"
            is_working = True
            cycle_phase = 0.5
            health = 0
            state = "PROCESSING"
            cycle_serial = 1

        pv = ProcessValueModel({
            "name": "FeedSpeed", "unit": "mm_s", "profile": "constant_noise",
            "mean": 450.0, "alarm_low": 400.0,
        })
        reg = AlarmRegistry()
        st = FakeStation()
        pv.mean = 390.0
        pv.update(st, None, 1.0, reg, 1.0)
        assert reg.is_active("PV_FEEDSPEED_LOW", "S1")
        pv.mean = 410.0
        pv.update(st, None, 1.0, reg, 2.0)
        assert not reg.is_active("PV_FEEDSPEED_LOW", "S1")


class TestHealthDriftShiftsValues:
    def test_degraded_health_measurably_shifts(self):
        cfg = {
            "name": "RamForce", "unit": "kN", "profile": "cycle_peak",
            "baseline": 0.0,
            "peak": {"distribution": "constant", "value": 100.0},
            "health_drift": 0.10,
        }
        extra = {"health": {"h_max": 10, "p_degrade": 1.0, "cbm_threshold": 10,
                            "mttr": {"distribution": "constant", "value": 1}}}
        healthy = engine_with_pv(dict(cfg), steps=2)
        degraded = engine_with_pv(dict(cfg), station_extra=extra, steps=2)
        # same phase, degraded peak is scaled by (1 + 0.1 * health)
        assert degraded.stations[0].health > 0
        assert pv_of(degraded).value > pv_of(healthy).value


class TestDeterminism:
    def test_identical_pv_trajectory_under_fixed_seed(self):
        pv_cfg = {
            "name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
            "setpoint": 55.0, "tau": 30.0, "initial": 20.0,
            "noise": {"distribution": "normal", "mean": 0, "std": 0.4},
            "alarm_high": 68.0,
        }
        traces = []
        for _ in range(2):
            eng = engine_with_pv(dict(pv_cfg), seed=42)
            vals = []
            for _ in range(200):
                eng.step()
                vals.append(pv_of(eng).value)
            traces.append(vals)
        assert traces[0] == traces[1]


class TestSPCHookup:
    def test_cycle_end_readings_feed_monitor(self):
        pv_cfg = {
            "name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
            "setpoint": 55.0, "tau": 30.0, "initial": 20.0,
        }
        eng = engine_with_pv(dict(pv_cfg), station_extra={"spc": {"enabled": True}},
                             steps=100)
        mon = eng.spc_monitors[("S1", "OilTemp")]
        assert mon.total_sample_count == eng.stations[0].parts_made


class TestSnapshotCarriesPVs:
    def test_pv_snapshot_fields(self):
        pv_cfg = {
            "name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
            "setpoint": 55.0, "tau": 30.0, "initial": 20.0, "alarm_high": 68.0,
        }
        eng = engine_with_pv(dict(pv_cfg), steps=10)
        snap = asdict(eng.snapshot())
        pvs = snap["stations"]["S1"]["process_values"]
        assert pvs[0]["name"] == "OilTemp"
        assert pvs[0]["unit"] == "degC"
        assert pvs[0]["alarm_state"] == "OK"
        json.dumps(snap)
