"""Gate P2 — engine core: determinism, states, health, quality, cycle stops, OEE."""
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


class TestCbmRemoved:
    def test_former_cbm_config_now_reaches_failed(self):
        """Same station config TestCBM used to assert never failed — with
        cbm_threshold no longer read by anything, this must now behave as
        plain run-to-failure and actually reach FAILED/UNDER_REPAIR."""
        cfg = {
            "stations": [
                {
                    "name": "S1",
                    "cycle_time": 2.0,
                    "health": {
                        "h_max": 3,
                        "p_degrade": 1.0,
                        "mttr": {"distribution": "constant", "value": 4},
                    },
                },
                {"name": "S2", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 5}],
        }
        eng = LineEngine(cfg, "test", seed=7, run_id="cbm-removed")
        saw_failed_or_repair = False
        for _ in range(200):
            eng.step()
            if eng.stations[0].state in (FAILED, UNDER_REPAIR):
                saw_failed_or_repair = True
                break
        assert saw_failed_or_repair
        assert eng.stations[0].time_in_state.get(FAILED, 0) > 0


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


class TestPerformanceFactor:
    """LineEngine.step(performance_factor=...) — the shift cycle_time_factor
    mechanism. Plain deterministic input (like speed_ratio), not randomness;
    the engine has no concept of "shifts", just a per-step multiplier.

    Single station, infinite source/sink (buffers=[]), so completions are
    exactly traceable: pulls at step 0 (cycle_elapsed=0), then cycle_elapsed
    advances by sim_step each step until it reaches effective_cycle_time
    (cycle_time * performance_factor), at which point _complete_cycle() fires
    and — since downstream is None, always "has space" — the finished part is
    pushed and a new one pulled within that same step.
    """

    def one_station_config(self):
        return {
            "stations": [{"name": "S1", "cycle_time": 5.0}],
            "buffers": [],
        }

    def test_default_matches_nameplate_pace(self):
        """factor=1.0 (the default): completions every cycle_time steps —
        same 19-completions-in-100-steps arithmetic as the hand-computed OEE
        test above, confirming the single-station harness matches it."""
        eng = LineEngine(self.one_station_config(), "test", seed=1)
        for _ in range(100):
            eng.step()
        s1 = eng.stations[0]
        assert s1.parts_made == 19
        assert abs(s1.kpis()["performance"] - 0.95) < 1e-9

    def test_factor_slows_completion_and_drops_measured_performance(self):
        """factor=2.0 doubles effective_cycle_time (5.0 -> 10.0): completions
        every 10 steps instead of 5, so only 9 land in 100 steps (steps
        10,20,...,90 — the 10th would land at step 100, past the run).

        kpis()['performance'] must use the NAMEPLATE cycle_time (5.0) as the
        denominator, not the slowed effective one — that's what makes the
        factor's effect on real output visible as a measured Performance
        drop (0.95 -> 0.45) rather than invisible (which is what would
        happen if cycle_time itself were multiplied and used consistently
        everywhere: measured pace would always equal 100% of "rated" pace,
        by definition, no matter how slow "rated" was redefined to be).
        """
        eng = LineEngine(self.one_station_config(), "test", seed=1)
        for _ in range(100):
            eng.step(performance_factor=2.0)
        s1 = eng.stations[0]
        assert s1.parts_made == 9
        assert s1.cycle_time == 5.0  # nameplate untouched
        assert abs(s1.kpis()["performance"] - 0.45) < 1e-9

    def test_factor_speeds_up_completion(self):
        """factor<1.0 is symmetric: effective_cycle_time 5.0*0.5=2.5, so a
        completion every 3 steps (ceil, since cycle_elapsed is checked after
        each 1.0 increment: 2.5 is first reached/exceeded at elapsed=3.0)."""
        eng = LineEngine(self.one_station_config(), "test", seed=1)
        for _ in range(12):
            eng.step(performance_factor=0.5)
        # completions at step indices 3, 6, 9 (elapsed hits 3.0 >= 2.5 each
        # cycle); the 4th would land at index 12, one past this 12-call run
        assert eng.stations[0].parts_made == 3

    def test_cycle_phase_reflects_effective_not_nameplate_cycle_time(self):
        """Same physical progress (2 sim-seconds into a 5-second nameplate
        cycle) must report a LOWER phase when a factor slows the effective
        cycle — otherwise the HMI progress bar would claim a station is
        further along than it actually is."""
        baseline = LineEngine(self.one_station_config(), "test", seed=1)
        slowed = LineEngine(self.one_station_config(), "test", seed=1)
        for _ in range(3):  # steps 0,1,2 -> cycle_elapsed == 2.0 in both
            baseline.step(performance_factor=1.0)
            slowed.step(performance_factor=2.0)

        assert baseline.stations[0].cycle_elapsed == 2.0
        assert slowed.stations[0].cycle_elapsed == 2.0
        assert abs(baseline.stations[0].cycle_phase - 0.4) < 1e-9   # 2.0/5.0
        assert abs(slowed.stations[0].cycle_phase - 0.2) < 1e-9     # 2.0/10.0

    def test_default_kwarg_identical_to_explicit_1_0(self):
        """Backward compatibility: an omitted performance_factor must be
        byte-identical to explicitly passing 1.0 — same RNG draws, same
        state, since the factor only touches the completion threshold, never
        the per-step RNG seeding (P4.4 determinism)."""
        a = LineEngine(self.one_station_config(), "test", seed=7)
        b = LineEngine(self.one_station_config(), "test", seed=7)
        for _ in range(50):
            a.step()
            b.step(performance_factor=1.0)
        assert a.stations[0].parts_made == b.stations[0].parts_made
        assert a.stations[0].cycle_elapsed == b.stations[0].cycle_elapsed


class TestHealthDegradeFactor:
    """LineEngine.step(health_degrade_factor=...) — the shift
    health_degrade_factor mechanism. Scales p_degrade only (clamped to
    [0, 1]); repair sampling and failure-mode attribution are untouched.
    Deterministic edge-case probabilities (0.0 and a clamped-to-1.0 case)
    rather than statistical sampling, same style as TestRunToFailure.
    """

    def cfg(self, p_degrade, mttr=5):
        return {
            "stations": [
                {
                    "name": "S1",
                    "cycle_time": 2.0,
                    "health": {
                        "h_max": 3,
                        "p_degrade": p_degrade,
                        "mttr": {"distribution": "constant", "value": mttr},
                    },
                },
                {"name": "S2", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 5}],
        }

    def test_factor_clamped_to_1_0_reproduces_p_degrade_1_0_trajectory(self):
        """p_degrade=0.5, factor=2.0 -> effective p=1.0 (clamped), so this
        must reproduce TestRunToFailure's p_degrade=1.0 trajectory exactly:
        health 1,2,3 -> FAILED on the 3rd step, 5 steps UNDER_REPAIR."""
        eng = LineEngine(self.cfg(p_degrade=0.5, mttr=5), "test", seed=7, run_id="hdf")
        states, healths = [], []
        for _ in range(12):
            eng.step(health_degrade_factor=2.0)
            states.append(eng.stations[0].state)
            healths.append(eng.stations[0].health)
        assert healths[:3] == [1, 2, 3]
        assert states[2] == FAILED
        assert states[3:8] == [UNDER_REPAIR] * 5
        assert healths[8] == 0

    def test_factor_0_never_degrades(self):
        """p_degrade=1.0 would normally fail on step 1; factor=0.0 must
        suppress degradation entirely, indefinitely."""
        eng = LineEngine(self.cfg(p_degrade=1.0), "test", seed=7, run_id="hdf0")
        for _ in range(30):
            eng.step(health_degrade_factor=0.0)
        assert eng.stations[0].health == 0
        assert eng.stations[0].state != FAILED

    def test_default_factor_matches_nameplate_p_degrade(self):
        """Omitting health_degrade_factor must reproduce
        TestRunToFailure's own p_degrade=1.0 trajectory unchanged."""
        eng = LineEngine(self.cfg(p_degrade=1.0, mttr=5), "test", seed=7, run_id="hdf_def")
        states, healths = [], []
        for _ in range(12):
            eng.step()
            states.append(eng.stations[0].state)
            healths.append(eng.stations[0].health)
        assert healths[:3] == [1, 2, 3]
        assert states[2] == FAILED
        assert states[3:8] == [UNDER_REPAIR] * 5
        assert healths[8] == 0

    def test_factor_does_not_affect_repair_or_attribution(self):
        """Once failed, the repair countdown and recovery must be unaffected
        by whatever health_degrade_factor is passed on later steps — the
        factor is only consulted while health < h_max and not repairing.
        Pre-failure steps use a constant factor=1.0 (the well-established
        p_degrade=1.0 trajectory: health 1,2,3 -> FAILED at step index 2);
        only the post-failure steps vary the factor wildly."""
        eng = LineEngine(self.cfg(p_degrade=1.0, mttr=5), "test", seed=7, run_id="hdf_rep")
        states = []
        varying_factors = [0.0, 5.0, 1.0, 0.0, 5.0, 1.0, 0.0, 5.0, 1.0]
        for i in range(12):
            factor = 1.0 if i < 3 else varying_factors[(i - 3) % len(varying_factors)]
            eng.step(health_degrade_factor=factor)
            states.append(eng.stations[0].state)
        assert states[2] == FAILED
        assert states[3:8] == [UNDER_REPAIR] * 5
        # health resets to 0 exactly when repair completes at step index 7,
        # regardless of the chaotic post-failure factor sequence above
        assert states[8] not in (FAILED, UNDER_REPAIR)


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


class TestEngineBoundedMemory:
    """Regression for the soak-run residual leak: the engine must hold no
    per-step-growing containers over arbitrarily long runs."""

    @staticmethod
    def _container_sizes(eng):
        sizes = {}
        for attr, value in vars(eng.alarms).items():
            if isinstance(value, (list, dict)):
                sizes[f"alarms.{attr}"] = len(value)
        return sizes

    def test_alarm_registry_bounded_under_churn(self):
        # stochastic_config exercises FM raise/clear, MT_REPAIR, and CS churn
        eng = LineEngine(stochastic_config(), "test", seed=3, run_id="bounded")
        for _ in range(2_000):
            eng.step()
        sizes_2k = self._container_sizes(eng)
        for _ in range(8_000):
            eng.step()
        sizes_10k = self._container_sizes(eng)
        for name, size in sizes_10k.items():
            # active set is bounded by (stations x codes); nothing may scale
            # with elapsed steps
            assert size <= max(sizes_2k.get(name, 0), 32), (
                f"{name} grew with run length: {sizes_2k.get(name)} -> {size}")
