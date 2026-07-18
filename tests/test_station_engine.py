"""Gate P2 — engine core: determinism, states, health, CBM, quality, cycle stops, OEE."""
import json
from dataclasses import asdict

import pytest

from simengine.engine.line import LineEngine
from simengine.engine.station import (
    BLOCKED,
    FAILED,
    PROCESSING,
    STARVED,
    UNDER_REPAIR,
    StationModel,
)


def two_station_config(**overrides):
    cfg = {
        "stations": [
            {"name": "S1", "cycle_time": 2.0},
            {"name": "S2", "cycle_time": 2.0},
        ],
        "buffers": [{"name": "B1", "capacity": 5}],
    }
    cfg.update(overrides)
    return cfg


def stochastic_config():
    """Every stochastic feature on, for determinism hashing."""
    return {
        "stations": [
            {
                "name": "S1",
                "cycle_time": 3.0,
                "defect_rate": 0.1,
                "health": {
                    "h_max": 3,
                    "p_degrade": 0.05,
                    "cbm_threshold": 3,
                    "mttr": {"distribution": "lognormal", "mean": 8, "std": 2},
                },
                "failure_modes": [
                    {
                        "name": "bearing_wear",
                        "type": "wearout",
                        "mttf": {"distribution": "weibull", "shape": 2.0, "scale": 500},
                        "mttr": {"distribution": "lognormal", "mean": 6, "std": 2},
                    }
                ],
                "cycle_stops": [
                    {
                        "reason": "CS_JAM",
                        "mtbe": {"distribution": "exponential", "mean": 40},
                        "duration": {"distribution": "lognormal", "mean": 5, "std": 2},
                    }
                ],
            },
            {"name": "S2", "cycle_time": 2.0, "defect_rate": 0.05},
        ],
        "buffers": [{"name": "B1", "capacity": 4}],
    }


def run_engine(config, seed, steps, run_id="test"):
    eng = LineEngine(config, "test", seed=seed, run_id=run_id)
    for _ in range(steps):
        eng.step()
    return eng


class TestDeterminism:
    def test_identical_trajectory_same_seed(self):
        hashes = []
        for _ in range(2):
            eng = LineEngine(stochastic_config(), "test", seed=42, run_id="det")
            h = 0
            for _ in range(1000):
                eng.step()
                h = hash((h, json.dumps(asdict(eng.snapshot()), sort_keys=True)))
            hashes.append(h)
        assert hashes[0] == hashes[1]

    def test_different_seed_diverges(self):
        snaps = []
        for seed in (1, 2):
            eng = run_engine(stochastic_config(), seed, 500)
            snaps.append(json.dumps(asdict(eng.snapshot()), sort_keys=True))
        assert snaps[0] != snaps[1]


class TestStarvationBlocking:
    def test_downstream_starved(self):
        cfg = {
            "stations": [
                {"name": "Slow", "cycle_time": 10.0},
                {"name": "Fast", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 2}],
        }
        eng = run_engine(cfg, 1, 50)
        starved = eng.stations[1].time_in_state.get(STARVED, 0.0)
        assert starved > 0

    def test_upstream_blocked(self):
        cfg = {
            "stations": [
                {"name": "Fast", "cycle_time": 2.0},
                {"name": "Slow", "cycle_time": 10.0},
            ],
            "buffers": [{"name": "B1", "capacity": 1}],
        }
        eng = run_engine(cfg, 1, 50)
        blocked = eng.stations[0].time_in_state.get(BLOCKED, 0.0)
        assert blocked > 0


class TestRunToFailure:
    def cfg(self, mttr=5):
        return {
            "stations": [
                {
                    "name": "S1",
                    "cycle_time": 2.0,
                    "health": {
                        "h_max": 3,
                        "p_degrade": 1.0,
                        "cbm_threshold": 3,
                        "mttr": {"distribution": "constant", "value": mttr},
                    },
                },
                {"name": "S2", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 5}],
        }

    def test_fails_on_step_3_repairs_and_recovers(self):
        eng = LineEngine(self.cfg(mttr=5), "test", seed=7, run_id="rtf")
        states = []
        healths = []
        for _ in range(12):
            eng.step()
            states.append(eng.stations[0].state)
            healths.append(eng.stations[0].health)
        # p_degrade=1: health 1,2,3 -> FAILED on 3rd step (index 2)
        assert healths[:3] == [1, 2, 3]
        assert states[2] == FAILED
        # repair sampled next step; UNDER_REPAIR for ceil(5) steps
        assert states[3:8] == [UNDER_REPAIR] * 5
        # recovered to health 0 on the completion step
        assert healths[8] == 0
        assert states[8] not in (FAILED, UNDER_REPAIR)

    def test_downtime_accumulates(self):
        # 11 steps: degrade 0-1, FAILED at 2, UNDER_REPAIR 3-7, healthy 8, degrade 9-10
        eng = run_engine(self.cfg(mttr=5), 7, 11)
        tis = eng.stations[0].time_in_state
        assert tis.get(FAILED, 0) == 1.0
        assert tis.get(UNDER_REPAIR, 0) == 5.0


class TestCBM:
    def test_never_reaches_failed(self):
        cfg = {
            "stations": [
                {
                    "name": "S1",
                    "cycle_time": 2.0,
                    "health": {
                        "h_max": 3,
                        "p_degrade": 1.0,
                        "cbm_threshold": 2,
                        "mttr": {"distribution": "constant", "value": 4},
                    },
                },
                {"name": "S2", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 5}],
        }
        eng = LineEngine(cfg, "test", seed=7, run_id="cbm")
        for _ in range(200):
            eng.step()
            st = eng.stations[0]
            assert st.state not in (FAILED, UNDER_REPAIR)
            assert st.health < st.h_max
        # health cycles back to 0 after each CBM repair
        assert eng.stations[0].time_in_state.get(FAILED, 0) == 0


class TestQualityConservation:
    def test_no_rework(self):
        cfg = two_station_config()
        cfg["stations"][0]["defect_rate"] = 0.3
        cfg["stations"][1]["defect_rate"] = 0.2
        eng = run_engine(cfg, 3, 600)
        for st in eng.stations:
            assert st.good + st.scrap == st.parts_made
            assert st.defective == st.scrap  # no rework configured
            assert st.scrap > 0  # 0.2+ defect rate over hundreds of cycles

    def test_with_rework(self):
        st = StationModel(
            {"name": "S1", "cycle_time": 1.0, "defect_rate": 0.5},
            rework_enabled=True, rework_success_rate=0.5,
        )
        import random
        rng = random.Random(11)
        for _ in range(500):
            st.has_part = True
            st.part_ready = False
            st.cycle_elapsed = st.cycle_time
            st._complete_cycle(rng, counting=True)
        assert st.good + st.scrap == st.parts_made
        assert st.defective == st.rework + st.scrap
        assert st.rework > 0 and st.scrap > 0


class TestCycleStops:
    def cfg(self):
        return {
            "stations": [
                {
                    "name": "S1",
                    "cycle_time": 2.0,
                    "cycle_stops": [
                        {
                            "reason": "CS_JAM",
                            "mtbe": {"distribution": "constant", "value": 5},
                            "duration": {"distribution": "constant", "value": 3},
                        }
                    ],
                },
                {"name": "S2", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 5}],
        }

    def test_fires_halts_clears_refires(self):
        eng = LineEngine(self.cfg(), "test", seed=5, run_id="cs")
        active_periods = 0
        prev_active = False
        elapsed_during_stop = []
        for _ in range(60):
            eng.step()
            active = eng.alarms.is_active("CS_JAM", "S1")
            if active and not prev_active:
                active_periods += 1
                stop_start_elapsed = eng.stations[0].cycle_elapsed
            if active:
                elapsed_during_stop.append(
                    (eng.stations[0].cycle_elapsed, stop_start_elapsed)
                )
            prev_active = active
        assert active_periods >= 2  # fired, cleared, refired
        # cycle progress halted while stopped
        assert all(e == s for e, s in elapsed_during_stop)

    def test_minor_stop_time_bucket(self):
        eng = run_engine(self.cfg(), 5, 60)
        assert eng.stations[0].time_in_state.get("MINOR_STOP", 0) > 0


class TestOEE:
    def test_hand_computed_100_steps(self):
        """Deterministic scripted scenario, hand-computed to 1e-9.

        Two stations, cycle_time 5, no defects, no failures. Steps run at
        indices 0..99.
        S1: pulls at step 0, completes at steps 5,10,...,95 -> 19 parts,
            PROCESSING 100% of the time -> A=1, P=(19*5)/100=0.95, Q=1.
        S2: STARVED steps 0-5 (S1's first push lands at step 5, S2 steps
            downstream-first so it pulls at step 6), then completes at
            steps 11,16,...,96 -> 18 parts.
            A=1 (no downtime), P=(18*5)/100=0.9, Q=1, OEE=0.9.
        Line (bottleneck min): A=1, P=0.9, Q=1, OEE=0.9.
        """
        cfg = {
            "stations": [
                {"name": "S1", "cycle_time": 5.0},
                {"name": "S2", "cycle_time": 5.0},
            ],
            "buffers": [{"name": "B1", "capacity": 10}],
        }
        eng = run_engine(cfg, 1, 100)
        s1, s2 = eng.stations
        assert s1.parts_made == 19
        assert s2.parts_made == 18
        assert s2.time_in_state.get(STARVED, 0) == 6.0
        assert s2.time_in_state.get(PROCESSING, 0) == 94.0

        k1, k2 = s1.kpis(), s2.kpis()
        assert abs(k1["availability"] - 1.0) < 1e-9
        assert abs(k1["performance"] - 0.95) < 1e-9
        assert abs(k1["quality"] - 1.0) < 1e-9
        assert abs(k1["oee"] - 0.95) < 1e-9
        assert abs(k2["availability"] - 1.0) < 1e-9
        assert abs(k2["performance"] - 0.9) < 1e-9
        assert abs(k2["oee"] - 0.9) < 1e-9

        snap = eng.snapshot()
        assert abs(snap.oee - 0.9) < 1e-9

    def test_downtime_reduces_availability(self):
        cfg = {
            "stations": [
                {
                    "name": "S1",
                    "cycle_time": 2.0,
                    "health": {
                        "h_max": 2,
                        "p_degrade": 0.2,
                        "cbm_threshold": 2,
                        "mttr": {"distribution": "constant", "value": 10},
                    },
                },
                {"name": "S2", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 5}],
        }
        eng = run_engine(cfg, 9, 400)
        k = eng.stations[0].kpis()
        tis = eng.stations[0].time_in_state
        down = tis.get(FAILED, 0) + tis.get(UNDER_REPAIR, 0)
        assert down > 0
        assert abs(k["availability"] - (1 - down / sum(tis.values()))) < 1e-9


class TestWarmUp:
    def test_counters_gated_during_warm_up(self):
        cfg = two_station_config(warm_up_time=50)
        eng = run_engine(cfg, 1, 50)
        assert all(st.parts_made == 0 for st in eng.stations)
        assert all(st.time_in_state == {} for st in eng.stations)
        for _ in range(50):
            eng.step()
        assert eng.stations[0].parts_made > 0


class TestSnapshotIntegration:
    def test_snapshot_shape(self):
        eng = run_engine(stochastic_config(), 42, 100)
        snap = eng.snapshot()
        d = asdict(snap)
        json.dumps(d)  # serializable
        assert set(d["stations"].keys()) == {"S1", "S2"}
        assert d["buffers"]["B1"]["capacity"] == 4
        assert 0 <= d["stations"]["S1"]["cycle_phase"] <= 1.0
        assert d["step_count"] == 100
