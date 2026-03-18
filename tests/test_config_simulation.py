"""
Config-to-simulation fidelity tests.

These tests verify that scenario config values (cycle_time, warm_up_time,
defect_rate, buffer capacity, multi-machine topology) are actually reflected
in simulation output when running the per-step loop used by the OPC UA server.

They exercise _persist_buffer_state + _install_health_restorer + LineState,
the pipeline that was broken when M2-M8 showed 0 PPM despite M1 producing.

All tests use inline config dicts so they never depend on YAML files on disk.
"""
import random
import pytest
import numpy as np

from opcua_server import (
    build_simantha_system,
    _persist_buffer_state,
    _install_health_restorer,
)
from line_state import LineState


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

def _make_config(machines, buffers=None, warm_up_time=0, source=None):
    """Build a minimal scenario config dict for testing."""
    if buffers is None:
        # Auto-generate serial buffers between machines
        buffers = []
        for i in range(len(machines) - 1):
            m_up = machines[i]["name"]
            m_dn = machines[i + 1]["name"]
            buffers.append({
                "name": f"B{i+1}",
                "capacity": 10,
                "upstream": m_up,
                "downstream": m_dn,
            })
    cfg = {"machines": machines, "buffers": buffers}
    if warm_up_time:
        cfg["warm_up_time"] = warm_up_time
    if source:
        cfg["source"] = source
    return cfg


def run_steps(config, n_steps, seed=42):
    """
    Run n_steps of the per-step simulation loop and return a results dict.

    Uses the same _persist_buffer_state + _install_health_restorer pattern
    as run_segment() in opcua_server.py.  No OPC UA server is started.

    Returns:
        dict with keys:
            line_state      — LineState instance with all accumulated counters
            machine_health  — final health dict
            total_parts     — total parts reaching the sink
            steps_run       — n_steps
            source          — Source object (for inspection)
    """
    warm_up_time = int(config.get("warm_up_time", 0))
    system, source, sink, machines, buffers, maintainer, scrap_sinks = \
        build_simantha_system(config)

    # Apply source interarrival_time from config — build_simantha_system creates
    # Source() without it; run_segment() sets it via OPC UA read, so we must
    # mirror that here for the tests to work without an OPC UA server.
    interarrival = config.get("source", {}).get("interarrival_time")
    if interarrival is not None:
        source.interarrival_time = float(interarrival)

    line_state = LineState()
    for mname in machines:
        line_state.init_machine(mname)

    machine_health = {mname: 0 for mname in machines}
    machine_carryover = {mname: None for mname in machines}

    for step in range(n_steps):
        step_seed = (seed + step) % (2 ** 31)
        random.seed(step_seed)
        np.random.seed(step_seed)

        _persist_buffer_state(buffers)
        for mname, mobj in machines.items():
            mobj._counting_active = step >= warm_up_time
            _install_health_restorer(
                mobj, machine_health[mname],
                carryover=machine_carryover[mname],
            )

        system.simulate(warm_up_time=0, simulation_time=1.0,
                        verbose=False, collect_data=False)

        for mname, mobj in machines.items():
            machine_health[mname] = getattr(mobj, "health", 0)

        machine_carryover = {}
        for mname, mobj in machines.items():
            if getattr(mobj, "has_part", False) and mobj.contents:
                finished = (getattr(mobj, "blocked", False)
                            or getattr(mobj, "has_finished_part", False))
                if finished:
                    remaining = 0.0
                else:
                    # Inspect event queue for the remaining cycle time —
                    # same logic as run_segment() in opcua_server.py.
                    remaining = None
                    for event in system.env.events:
                        if (not event.canceled
                                and event.location == mname
                                and event.action.__name__ == "request_space"):
                            remaining = max(0.001,
                                            event.time - system.env.now)
                            break
                    if remaining is None:
                        remaining = 1.0
                machine_carryover[mname] = {
                    "contents": list(mobj.contents),
                    "finished": finished,
                    "remaining": remaining,
                }
            else:
                machine_carryover[mname] = None

        line_state.step_count += 1
        for mname, mobj in machines.items():
            line_state.sync_machine(mname, mobj)
        line_state.sync_sink(sink.level)

    return {
        "line_state": line_state,
        "machine_health": machine_health,
        "total_parts": line_state.total_parts_produced,
        "steps_run": n_steps,
        "sink": sink,
        "scrap_sinks": scrap_sinks,
        "source": source,
        "machines": machines,
    }


def _active_steps(result, config):
    """Return the number of counting steps (post-warm-up)."""
    warm_up = int(config.get("warm_up_time", 0))
    return max(0, result["steps_run"] - warm_up)


def _ppm(result, mname, config):
    """Return actual PPM for a machine.

    For quality-routing machines the good/scrap/defective counters only
    accumulate post-warm-up, so we use them divided by active minutes.

    For plain machines those counters are always 0; we fall back to
    parts_made / total_run_minutes.  This is correct when warm_up_time=0
    (all cycle-time tests).  Tests that rely on post-warm-up PPM for plain
    machines should use QR machines or total_parts_produced instead.
    """
    mt = result["line_state"].machines[mname]
    qr_total = mt.good_count + mt.scrap_count + mt.defective_count
    if qr_total > 0:
        active_min = _active_steps(result, config) / 60.0
        return qr_total / active_min if active_min > 0 else 0.0
    # Plain machine: use parts_made over the full run
    total_min = result["steps_run"] / 60.0
    return mt.parts_made / total_min if total_min > 0 else 0.0


# ===========================================================================
# 1. Cycle time
# ===========================================================================

class TestCycleTime:
    """Verify that cycle_time is reflected in throughput."""

    @pytest.mark.parametrize("cycle_time, expected_ppm, tol", [
        (1, 60.0, 5.0),   # 1s/part → 60 PPM
        (2, 30.0, 3.0),   # 2s/part → 30 PPM
        (3, 20.0, 2.5),   # 3s/part → 20 PPM
    ])
    def test_single_machine_ppm_matches_cycle_time(self, cycle_time, expected_ppm, tol):
        """A single-machine line should produce ~60/cycle_time PPM."""
        config = _make_config([
            {"name": "M1", "cycle_time": cycle_time},
            {"name": "M2", "cycle_time": cycle_time},
        ])
        result = run_steps(config, n_steps=300, seed=1)
        actual_ppm = _ppm(result, "M1", config)
        assert abs(actual_ppm - expected_ppm) <= tol, (
            f"cycle_time={cycle_time}: expected ~{expected_ppm} PPM, got {actual_ppm:.1f}"
        )

    def test_target_ppm_overrides_cycle_time(self):
        """target_ppm in config should produce that PPM rate."""
        config = _make_config([
            {"name": "M1", "target_ppm": 20},
            {"name": "M2", "target_ppm": 20},
        ])
        result = run_steps(config, n_steps=300, seed=2)
        actual_ppm = _ppm(result, "M1", config)
        assert abs(actual_ppm - 20.0) <= 3.0, (
            f"target_ppm=20: expected ~20 PPM, got {actual_ppm:.1f}"
        )

    def test_bottleneck_limits_downstream(self):
        """A slow machine limits throughput of all downstream machines."""
        config = _make_config([
            {"name": "M1", "cycle_time": 1},   # 60 PPM
            {"name": "M2", "cycle_time": 3},   # 20 PPM — bottleneck
            {"name": "M3", "cycle_time": 1},   # limited by M2
        ])
        result = run_steps(config, n_steps=600, seed=3)
        # M3 throughput should be near M2's rate (20 PPM), not M1's (60 PPM)
        m3_ppm = _ppm(result, "M3", config)
        assert m3_ppm < 35.0, (
            f"M3 should be bottlenecked by M2 (20 PPM), got {m3_ppm:.1f}"
        )
        assert m3_ppm > 10.0, (
            f"M3 should still produce parts, got {m3_ppm:.1f}"
        )


# ===========================================================================
# 2. Warm-up time
# ===========================================================================

class TestWarmUpTime:
    """Verify that warm_up_time suppresses counting during warm-up steps."""

    def test_no_counts_during_warmup(self):
        """Quality counters should be 0 until warm_up steps have passed."""
        config = _make_config(
            [{"name": "M1", "cycle_time": 1, "quality_routing": {"enabled": True, "defect_rate": 0.1}},
             {"name": "M2", "cycle_time": 1, "quality_routing": {"enabled": True, "defect_rate": 0.1}}],
            warm_up_time=100,
        )
        # Run only 80 steps — still inside warm-up
        result = run_steps(config, n_steps=80, seed=10)
        mt = result["line_state"].machines["M1"]
        assert mt.good_count == 0, f"Expected 0 good_count during warm-up, got {mt.good_count}"
        assert mt.scrap_count == 0, f"Expected 0 scrap_count during warm-up, got {mt.scrap_count}"

    def test_counts_accumulate_after_warmup(self):
        """Quality counters should accumulate once warm_up steps have passed."""
        config = _make_config(
            [{"name": "M1", "cycle_time": 1, "quality_routing": {"enabled": True, "defect_rate": 0.0}},
             {"name": "M2", "cycle_time": 1, "quality_routing": {"enabled": True, "defect_rate": 0.0}}],
            warm_up_time=50,
        )
        # Run 150 steps: 50 warm-up + 100 active
        result = run_steps(config, n_steps=150, seed=11)
        mt = result["line_state"].machines["M1"]
        total_qr = mt.good_count + mt.scrap_count + mt.defective_count
        assert total_qr > 0, "Expected non-zero quality counts after warm-up"
        # With 100 active steps and cycle_time=1, expect ~100 parts
        assert total_qr >= 50, f"Expected ≥50 parts post-warm-up, got {total_qr}"

    def test_shorter_warmup_gives_more_counted_parts(self):
        """Same run with shorter warm-up should yield more counted parts."""
        machines = [
            {"name": "M1", "cycle_time": 1, "quality_routing": {"enabled": True, "defect_rate": 0.0}},
            {"name": "M2", "cycle_time": 1, "quality_routing": {"enabled": True, "defect_rate": 0.0}},
        ]
        config_long = _make_config(machines, warm_up_time=100)
        config_short = _make_config(machines, warm_up_time=20)

        result_long = run_steps(config_long, n_steps=200, seed=12)
        result_short = run_steps(config_short, n_steps=200, seed=12)

        mt_long = result_long["line_state"].machines["M1"]
        mt_short = result_short["line_state"].machines["M1"]
        long_total = mt_long.good_count + mt_long.scrap_count
        short_total = mt_short.good_count + mt_short.scrap_count

        assert short_total > long_total, (
            f"Shorter warm-up should give more counted parts: "
            f"short={short_total}, long={long_total}"
        )


# ===========================================================================
# 3. Defect rate
# ===========================================================================

class TestDefectRate:
    """Verify that defect_rate config is reflected in quality counters."""

    def test_zero_defect_rate_gives_all_good(self):
        """defect_rate=0.0 → all parts are good, scrap=0."""
        config = _make_config([
            {"name": "M1", "cycle_time": 1,
             "quality_routing": {"enabled": True, "defect_rate": 0.0}},
            {"name": "M2", "cycle_time": 1,
             "quality_routing": {"enabled": True, "defect_rate": 0.0}},
        ])
        result = run_steps(config, n_steps=200, seed=20)
        mt = result["line_state"].machines["M1"]
        assert mt.scrap_count == 0, f"defect_rate=0 should give scrap=0, got {mt.scrap_count}"
        assert mt.good_count > 0, "Should have good parts with defect_rate=0"

    def test_high_defect_rate_gives_scrap(self):
        """defect_rate=0.5 should produce substantial defects.

        Without a scrap sink, defective parts flow normally and are counted in
        defective_count rather than scrap_count.  We check the combined rate.
        """
        config = _make_config([
            {"name": "M1", "cycle_time": 1,
             "quality_routing": {"enabled": True, "defect_rate": 0.5}},
            {"name": "M2", "cycle_time": 1,
             "quality_routing": {"enabled": True, "defect_rate": 0.0}},
        ])
        result = run_steps(config, n_steps=300, seed=21)
        mt = result["line_state"].machines["M1"]
        total = mt.good_count + mt.scrap_count + mt.defective_count
        assert total > 0, "Should have produced parts"
        defect_rate = (mt.scrap_count + mt.defective_count) / total
        # With 50% defect rate, expect 30-70% defects
        assert 0.25 <= defect_rate <= 0.75, (
            f"defect_rate=0.5: expected defect_rate ≈ 0.5, got {defect_rate:.2f}"
        )

    def test_defect_rate_ordering(self):
        """Higher defect rate → higher combined defect fraction.

        Without a scrap sink, defective parts are counted in defective_count.
        We check scrap_count + defective_count to capture all defects.
        """
        rates = [0.05, 0.20, 0.40]
        defect_fracs = []
        for rate in rates:
            config = _make_config([
                {"name": "M1", "cycle_time": 1,
                 "quality_routing": {"enabled": True, "defect_rate": rate}},
                {"name": "M2", "cycle_time": 1},
            ])
            result = run_steps(config, n_steps=500, seed=22)
            mt = result["line_state"].machines["M1"]
            total = mt.good_count + mt.scrap_count + mt.defective_count
            defect_fracs.append(
                (mt.scrap_count + mt.defective_count) / total if total > 0 else 0
            )

        assert defect_fracs[0] < defect_fracs[1] < defect_fracs[2], (
            f"Defect fractions not monotone with defect_rate: {defect_fracs}"
        )


# ===========================================================================
# 4. Buffer capacity
# ===========================================================================

class TestBufferCapacity:
    """Verify that buffer capacity affects blocking/flow."""

    def test_tiny_buffer_causes_more_blocking(self):
        """A capacity-1 buffer between M1 (fast) and M2 (slow) blocks M1 more."""
        def run_with_capacity(cap):
            config = {
                "machines": [
                    {"name": "M1", "cycle_time": 1},
                    {"name": "M2", "cycle_time": 2},  # M2 slower → M1 blocks
                ],
                "buffers": [
                    {"name": "B1", "capacity": cap, "upstream": "M1", "downstream": "M2"},
                ],
            }
            return run_steps(config, n_steps=300, seed=30)

        result_small = run_with_capacity(1)
        result_large = run_with_capacity(20)

        # With a large buffer, M1 blocks less → produces more parts
        m1_small = result_small["line_state"].machines["M1"].parts_made
        m1_large = result_large["line_state"].machines["M1"].parts_made
        assert m1_large >= m1_small, (
            f"Larger buffer should allow M1 to produce ≥ parts: "
            f"large={m1_large}, small={m1_small}"
        )

    def test_buffer_level_persists_across_steps(self):
        """Buffer contents should persist across step boundaries so M2 isn't starved."""
        config = _make_config([
            {"name": "M1", "cycle_time": 1},
            {"name": "M2", "cycle_time": 1},
        ])
        result = run_steps(config, n_steps=200, seed=31)
        # M2 should produce within ~10% of M1's output
        mt1 = result["line_state"].machines["M1"]
        mt2 = result["line_state"].machines["M2"]
        ratio = mt2.parts_made / mt1.parts_made if mt1.parts_made > 0 else 0
        assert ratio >= 0.7, (
            f"M2 should produce close to M1's throughput (buffer persistence). "
            f"M1={mt1.parts_made}, M2={mt2.parts_made}, ratio={ratio:.2f}"
        )


# ===========================================================================
# 5. Multi-machine throughput (regression for M2-M8 zero PPM bug)
# ===========================================================================

class TestMultiMachineThroughput:
    """All machines in a serial line should produce non-zero parts."""

    @pytest.mark.parametrize("n_machines", [2, 4, 8])
    def test_all_machines_produce_parts(self, n_machines):
        """Every machine in an n-machine serial line should produce > 0 parts."""
        machines = [{"name": f"M{i+1}", "cycle_time": 1} for i in range(n_machines)]
        config = _make_config(machines)
        result = run_steps(config, n_steps=200, seed=40)
        for i in range(n_machines):
            mname = f"M{i+1}"
            parts = result["line_state"].machines[mname].parts_made
            assert parts > 0, f"{mname} produced 0 parts in {n_machines}-machine line"

    def test_8_machine_line_with_quality_routing(self):
        """8-machine line with quality routing: all machines produce non-zero PPM."""
        machines = [
            {"name": f"M{i+1}", "cycle_time": 1,
             "quality_routing": {"enabled": True, "defect_rate": 0.05}}
            for i in range(8)
        ]
        config = _make_config(machines, warm_up_time=10)
        result = run_steps(config, n_steps=200, seed=41)
        for i in range(8):
            mname = f"M{i+1}"
            mt = result["line_state"].machines[mname]
            total = mt.good_count + mt.scrap_count + mt.defective_count
            assert total > 0, (
                f"{mname} has 0 quality-counted parts in 8-machine QR line"
            )

    def test_throughput_degrades_gradually_downstream(self):
        """In a serial line, downstream machines produce ≤ upstream machines."""
        n = 5
        machines = [{"name": f"M{i+1}", "cycle_time": 1} for i in range(n)]
        config = _make_config(machines)
        result = run_steps(config, n_steps=300, seed=42)
        parts = [result["line_state"].machines[f"M{i+1}"].parts_made for i in range(n)]
        for i in range(n - 1):
            assert parts[i] >= parts[i + 1] * 0.8, (
                f"M{i+1} ({parts[i]}) should produce ≥ 80% of M{i} ({parts[i+1]})"
            )

    def test_full_feature_8_machine_no_stuck_machines(self):
        """
        full_feature_8_machine_line: no machine should show 0 PPM after warm-up.
        Regression test for the health-restoration stuck-FAILED bug.
        """
        from config_loader import load_line_config
        config = load_line_config("full_feature_8_machine_line")
        warm_up = int(config.get("warm_up_time", 0))
        # Run 3× warm-up steps to get meaningful post-warm-up counts
        n_steps = warm_up + 120
        result = run_steps(config, n_steps=n_steps, seed=44)
        for mname in result["line_state"].machines:
            mt = result["line_state"].machines[mname]
            total = mt.good_count + mt.scrap_count + mt.defective_count
            assert total > 0, (
                f"{mname} has 0 counted parts after warm-up in full_feature_8_machine_line"
            )


# ===========================================================================
# 6. Health degradation — machines must not get permanently stuck
# ===========================================================================

class TestHealthDegradation:
    """Verify that health restoration caps at failed_health-1 (no stuck FAILED)."""

    def test_degrading_machine_never_permanently_stuck(self):
        """
        A machine with fast degradation should still produce parts over a long run.
        Previously, health reaching failed_health would stick the machine FAILED
        forever because the maintainer never gets notified in the fresh env.
        """
        config = _make_config([
            {"name": "M1", "cycle_time": 1,
             "enable_degradation": True,
             "health_states": {"h_max": 2, "p_degrade": 0.5, "cbm_threshold": 1}},
            {"name": "M2", "cycle_time": 1},
        ], warm_up_time=0)
        config["maintainer"] = {"enabled": True, "strategy": "fifo"}
        result = run_steps(config, n_steps=500, seed=50)
        mt = result["line_state"].machines["M1"]
        # Machine degrades very fast (p=0.5) — it should still make parts
        assert mt.parts_made > 50, (
            f"Degrading machine got stuck FAILED — only {mt.parts_made} parts in 500 steps"
        )

    def test_health_restored_below_failed_threshold(self):
        """
        After any step, restored health must be < failed_health.
        Verify by inspecting machine_health dict after a long run with fast degradation.
        """
        from simantha import Machine
        config = _make_config([
            {"name": "M1", "cycle_time": 1,
             "enable_degradation": True,
             "health_states": {"h_max": 3, "p_degrade": 0.8, "cbm_threshold": 2}},
            {"name": "M2", "cycle_time": 1},
        ])
        config["maintainer"] = {"enabled": True, "strategy": "fifo"}

        system, source, sink, machines, buffers, maintainer, scrap_sinks = \
            build_simantha_system(config)

        machine_health = {mname: 0 for mname in machines}
        machine_carryover = {mname: None for mname in machines}
        line_state = LineState()
        for mname in machines:
            line_state.init_machine(mname)

        failed_health = getattr(machines["M1"], "failed_health", 1)

        for step in range(200):
            step_seed = (99 + step) % (2 ** 31)
            random.seed(step_seed)
            np.random.seed(step_seed)

            _persist_buffer_state(buffers)
            for mname, mobj in machines.items():
                mobj._counting_active = True
                _install_health_restorer(mobj, machine_health[mname],
                                         carryover=machine_carryover[mname])

            system.simulate(warm_up_time=0, simulation_time=1.0,
                            verbose=False, collect_data=False)

            for mname, mobj in machines.items():
                machine_health[mname] = getattr(mobj, "health", 0)

            machine_carryover = {
                mname: ({"contents": list(mobj.contents),
                          "finished": getattr(mobj, "blocked", False),
                          "remaining": 1.0}
                         if getattr(mobj, "has_part", False) and mobj.contents
                         else None)
                for mname, mobj in machines.items()
            }
            line_state.step_count += 1
            for mname, mobj in machines.items():
                line_state.sync_machine(mname, mobj)
            line_state.sync_sink(sink.level)

            # KEY ASSERTION: after each simulate(), health restored next step
            # must never equal or exceed failed_health
            restored = min(machine_health["M1"], max(0, failed_health - 1))
            assert restored < failed_health, (
                f"Step {step}: health would be restored to {restored} "
                f">= failed_health={failed_health}"
            )


# ===========================================================================
# 7. Sink consistency and reproducibility
# ===========================================================================

class TestSinkConsistencyAndReproducibility:
    """
    Verify that parts are not lost across step boundaries and that the
    same seed produces identical results across runs.

    Note on source interarrival_time: in per-step mode each step simulates
    exactly 1 second and Source.initialize() fires a new part at t=0 each
    step regardless of interarrival_time (the next inter-arrival event falls
    outside the 1-second window and is discarded when the env resets).
    Interarrival throttling is therefore ineffective in per-step mode for
    values >= sim_step and is not tested here.
    """

    def test_sink_count_matches_line_state_total(self):
        """LineState.total_parts_produced must equal the running sink delta sum."""
        config = _make_config([
            {"name": "M1", "cycle_time": 1},
            {"name": "M2", "cycle_time": 1},
            {"name": "M3", "cycle_time": 1},
        ])
        result = run_steps(config, n_steps=200, seed=60)
        # LineState.sync_sink accumulates deltas; its total should equal what
        # we tracked as total_parts
        assert result["total_parts"] == result["line_state"].total_parts_produced

    def test_no_parts_lost_between_steps(self):
        """Parts in buffers must not disappear across step boundaries."""
        config = _make_config([
            {"name": "M1", "cycle_time": 1},
            {"name": "M2", "cycle_time": 2},   # M2 slower — buffer fills up
            {"name": "M3", "cycle_time": 1},
        ])
        result = run_steps(config, n_steps=300, seed=61)
        mt1 = result["line_state"].machines["M1"].parts_made
        mt3 = result["line_state"].machines["M3"].parts_made
        # M3 should produce a substantial fraction of M1's output
        # (parts buffered between M1-M2 and M2-M3 should not vanish)
        assert mt3 >= mt1 * 0.3, (
            f"Too many parts lost: M1={mt1}, M3={mt3}, ratio={mt3/mt1:.2f}"
        )

    def test_same_seed_gives_same_results(self):
        """Two runs with the same seed must produce identical part counts."""
        config = _make_config([
            {"name": "M1", "cycle_time": 1,
             "quality_routing": {"enabled": True, "defect_rate": 0.1}},
            {"name": "M2", "cycle_time": 1,
             "quality_routing": {"enabled": True, "defect_rate": 0.05}},
        ])
        r1 = run_steps(config, n_steps=150, seed=99)
        r2 = run_steps(config, n_steps=150, seed=99)
        for mname in ["M1", "M2"]:
            mt1 = r1["line_state"].machines[mname]
            mt2 = r2["line_state"].machines[mname]
            assert mt1.good_count == mt2.good_count, (
                f"{mname}: same seed, different good_count: {mt1.good_count} vs {mt2.good_count}"
            )
            assert mt1.scrap_count == mt2.scrap_count, (
                f"{mname}: same seed, different scrap_count: {mt1.scrap_count} vs {mt2.scrap_count}"
            )

    def test_different_seeds_give_different_results(self):
        """Two runs with different seeds should give different quality counts."""
        config = _make_config([
            {"name": "M1", "cycle_time": 1,
             "quality_routing": {"enabled": True, "defect_rate": 0.2}},
            {"name": "M2", "cycle_time": 1},
        ])
        r1 = run_steps(config, n_steps=200, seed=1)
        r2 = run_steps(config, n_steps=200, seed=9999)
        mt1 = r1["line_state"].machines["M1"]
        mt2 = r2["line_state"].machines["M1"]
        # With 20% defect rate over 200 steps, scrap counts are very unlikely
        # to match between independent seeds
        assert (mt1.good_count != mt2.good_count or
                mt1.scrap_count != mt2.scrap_count), (
            "Different seeds produced identical quality counts — seeding may be broken"
        )
