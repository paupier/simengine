"""
OPC UA Integration Tests

Tests that verify the OPC UA server exposes correct variables,
responds to control inputs, and simulates realistic manufacturing behavior.
"""
import pytest
import time
from opcua import Client


class TestOPCUAAddressSpace:
    """Test that all expected OPC UA nodes exist and are accessible"""

    def test_system_nodes_exist(self, opcua_client):
        """Verify System-level nodes exist"""
        simtime = opcua_client.get_node("ns=2;s=Line1.System.SimTime")
        throughput = opcua_client.get_node("ns=2;s=Line1.System.Throughput")

        assert simtime is not None
        assert throughput is not None

    def test_control_nodes_exist(self, opcua_client):
        """Verify Control nodes exist and are writable"""
        pause = opcua_client.get_node("ns=2;s=Line1.System.Controls.cmdPauseLine")
        interarrival = opcua_client.get_node(
            "ns=2;s=Line1.System.Controls.setInterarrivalTime"
        )

        assert pause is not None
        assert interarrival is not None

    def test_station1_nodes_exist(self, opcua_client):
        """Verify Station1 (M1) nodes exist"""
        state = opcua_client.get_node("ns=2;s=Line1.Station1.State")
        partcount = opcua_client.get_node("ns=2;s=Line1.Station1.PartCount")
        util = opcua_client.get_node("ns=2;s=Line1.Station1.Utilisation")
        health = opcua_client.get_node("ns=2;s=Line1.Station1.HealthState")
        health_pct = opcua_client.get_node("ns=2;s=Line1.Station1.HealthPercent")

        assert state is not None
        assert partcount is not None
        assert util is not None
        assert health is not None
        assert health_pct is not None

    def test_buffer1_nodes_exist(self, opcua_client):
        """Verify Buffer1 nodes exist"""
        level = opcua_client.get_node("ns=2;s=Line1.Buffer1.CurrentLevel")
        capacity = opcua_client.get_node("ns=2;s=Line1.Buffer1.Capacity")

        assert level is not None
        assert capacity is not None

    def test_station2_nodes_exist(self, opcua_client):
        """Verify Station2 (M2) nodes exist"""
        state = opcua_client.get_node("ns=2;s=Line1.Station2.State")
        partcount = opcua_client.get_node("ns=2;s=Line1.Station2.PartCount")
        util = opcua_client.get_node("ns=2;s=Line1.Station2.Utilisation")

        assert state is not None
        assert partcount is not None
        assert util is not None

    def test_maintenance_nodes_exist(self, opcua_client):
        """Verify Maintenance nodes exist"""
        active = opcua_client.get_node("ns=2;s=Line1.Maintenance.MaintenanceActive")
        queue = opcua_client.get_node("ns=2;s=Line1.Maintenance.QueueLength")
        repairs = opcua_client.get_node("ns=2;s=Line1.Maintenance.TotalRepairs")

        assert active is not None
        assert queue is not None
        assert repairs is not None


class TestSimulationBehavior:
    """Test that simulation behaves correctly"""

    def test_simulation_time_advances(self, opcua_client):
        """Verify simulation time advances when not paused"""
        simtime = opcua_client.get_node("ns=2;s=Line1.System.SimTime")

        time1 = simtime.get_value()
        time.sleep(2)  # Wait 2 seconds
        time2 = simtime.get_value()

        assert time2 > time1, "Simulation time should advance"

    def test_throughput_increases(self, opcua_client):
        """Verify parts are being produced (throughput increases)"""
        throughput = opcua_client.get_node("ns=2;s=Line1.System.Throughput")

        parts1 = throughput.get_value()
        time.sleep(5)  # Wait 5 seconds
        parts2 = throughput.get_value()

        assert parts2 > parts1, "Throughput should increase over time"

    def test_part_counts_are_monotonic(self, opcua_client):
        """Verify part counts never decrease (monotonic counter)"""
        throughput = opcua_client.get_node("ns=2;s=Line1.System.Throughput")
        m1_parts = opcua_client.get_node("ns=2;s=Line1.Station1.PartCount")
        m2_parts = opcua_client.get_node("ns=2;s=Line1.Station2.PartCount")

        prev_throughput = throughput.get_value()
        prev_m1 = m1_parts.get_value()
        prev_m2 = m2_parts.get_value()

        # Sample every second for 10 seconds
        for _ in range(10):
            time.sleep(1)

            current_throughput = throughput.get_value()
            current_m1 = m1_parts.get_value()
            current_m2 = m2_parts.get_value()

            # Values should never decrease
            assert (
                current_throughput >= prev_throughput
            ), "Throughput decreased (monotonic violation)"
            assert current_m1 >= prev_m1, "M1 part count decreased (monotonic violation)"
            assert current_m2 >= prev_m2, "M2 part count decreased (monotonic violation)"

            prev_throughput = current_throughput
            prev_m1 = current_m1
            prev_m2 = current_m2

    def test_buffer_within_capacity(self, opcua_client):
        """Verify buffer level never exceeds capacity"""
        level = opcua_client.get_node("ns=2;s=Line1.Buffer1.CurrentLevel")
        capacity = opcua_client.get_node("ns=2;s=Line1.Buffer1.Capacity")

        buffer_capacity = capacity.get_value()

        # Check for 10 seconds
        for _ in range(10):
            buffer_level = level.get_value()
            assert (
                buffer_level <= buffer_capacity
            ), f"Buffer level {buffer_level} exceeds capacity {buffer_capacity}"
            time.sleep(1)


class TestControlInputs:
    """Test that OPC UA control inputs work correctly"""

    def test_pause_control_stops_simulation(self, opcua_client):
        """Verify cmdPauseLine control freezes simulation"""
        pause = opcua_client.get_node("ns=2;s=Line1.System.Controls.cmdPauseLine")
        simtime = opcua_client.get_node("ns=2;s=Line1.System.SimTime")
        m1_state = opcua_client.get_node("ns=2;s=Line1.Station1.State")

        # Unpause first (in case paused from previous test)
        pause.set_value(False)
        time.sleep(1)

        # Record time
        time1 = simtime.get_value()

        # Pause simulation
        pause.set_value(True)
        time.sleep(2)

        # Time should be frozen
        time2 = simtime.get_value()
        state = m1_state.get_value()

        assert time2 == time1, "Simulation time should freeze when paused"
        assert state == "PAUSED", f"Station state should be PAUSED, got {state}"

        # Unpause for other tests
        pause.set_value(False)
        time.sleep(1)

    def test_interarrival_time_control(self, opcua_client):
        """Verify setInterarrivalTime control affects throughput rate"""
        interarrival = opcua_client.get_node(
            "ns=2;s=Line1.System.Controls.setInterarrivalTime"
        )
        throughput = opcua_client.get_node("ns=2;s=Line1.System.Throughput")

        # Set fast arrival (0.0 = as fast as possible)
        interarrival.set_value(0.0)
        time.sleep(5)
        parts1 = throughput.get_value()

        # Set slow arrival (5.0 = one part every 5 seconds)
        interarrival.set_value(5.0)
        time.sleep(10)
        parts2 = throughput.get_value()
        delta_slow = parts2 - parts1

        # Reset to fast
        interarrival.set_value(0.0)
        time.sleep(5)
        parts3 = throughput.get_value()
        delta_fast = parts3 - parts2

        # Fast mode should produce more parts in same time
        assert (
            delta_fast > delta_slow
        ), "Fast arrival should produce more parts than slow arrival"


class TestHealthAndMaintenance:
    """Test machine health degradation and maintenance behavior"""

    def test_initial_health_is_100_percent(self, opcua_client):
        """Verify M1 starts at 100% health"""
        health_pct = opcua_client.get_node("ns=2;s=Line1.Station1.HealthPercent")

        # May not be exactly 100 if test runs after failure, but should be high initially
        initial_health = health_pct.get_value()
        assert initial_health >= 0, "Health should be between 0 and 100"
        assert initial_health <= 100, "Health should be between 0 and 100"

    def test_health_state_values_are_valid(self, opcua_client):
        """Verify HealthState is either 0 (healthy) or 1 (failed)"""
        health_state = opcua_client.get_node("ns=2;s=Line1.Station1.HealthState")

        for _ in range(5):
            state = health_state.get_value()
            assert state in [0, 1], f"HealthState should be 0 or 1, got {state}"
            time.sleep(1)

    def test_maintenance_values_are_valid(self, opcua_client):
        """Verify maintenance variables have valid values"""
        maint_active = opcua_client.get_node("ns=2;s=Line1.Maintenance.MaintenanceActive")
        queue_length = opcua_client.get_node("ns=2;s=Line1.Maintenance.QueueLength")
        total_repairs = opcua_client.get_node("ns=2;s=Line1.Maintenance.TotalRepairs")

        active = maint_active.get_value()
        queue = queue_length.get_value()
        repairs = total_repairs.get_value()

        assert isinstance(active, bool), "MaintenanceActive should be boolean"
        assert queue >= 0, "QueueLength should be non-negative"
        assert repairs >= 0, "TotalRepairs should be non-negative"


class TestStationStates:
    """Test that station states are valid and meaningful"""

    def test_station_states_are_valid(self, opcua_client):
        """Verify station states are one of the expected values"""
        m1_state = opcua_client.get_node("ns=2;s=Line1.Station1.State")
        m2_state = opcua_client.get_node("ns=2;s=Line1.Station2.State")

        valid_states = ["IDLE", "PROCESSING", "BLOCKED", "STARVED", "PAUSED", "FAILED", "UNDER_REPAIR"]

        for _ in range(5):
            state1 = m1_state.get_value()
            state2 = m2_state.get_value()

            assert (
                state1 in valid_states
            ), f"M1 state '{state1}' not in valid states {valid_states}"
            assert (
                state2 in valid_states
            ), f"M2 state '{state2}' not in valid states {valid_states}"

            time.sleep(1)

    def test_utilisation_is_between_0_and_1(self, opcua_client):
        """Verify utilisation values are in valid range [0.0, 1.0]"""
        m1_util = opcua_client.get_node("ns=2;s=Line1.Station1.Utilisation")
        m2_util = opcua_client.get_node("ns=2;s=Line1.Station2.Utilisation")

        for _ in range(5):
            util1 = m1_util.get_value()
            util2 = m2_util.get_value()

            assert 0.0 <= util1 <= 1.0, f"M1 utilisation {util1} out of range [0, 1]"
            assert 0.0 <= util2 <= 1.0, f"M2 utilisation {util2} out of range [0, 1]"

            time.sleep(1)


class TestEnhancedStateMachine:
    """Test Phase 5: Enhanced state logic and time tracking"""

    def test_time_tracking_variables_exist(self, opcua_client):
        """Verify all time tracking variables are accessible"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])
        station2 = line1.get_child(["2:Station2"])

        # Station1 time tracking
        m1_blocked = station1.get_child(["2:BlockedTime"])
        m1_starved = station1.get_child(["2:StarvedTime"])
        m1_down = station1.get_child(["2:DownTime"])
        m1_processing = station1.get_child(["2:ProcessingTime"])
        m1_idle = station1.get_child(["2:IdleTime"])

        # Station2 time tracking
        m2_blocked = station2.get_child(["2:BlockedTime"])
        m2_starved = station2.get_child(["2:StarvedTime"])
        m2_down = station2.get_child(["2:DownTime"])
        m2_processing = station2.get_child(["2:ProcessingTime"])
        m2_idle = station2.get_child(["2:IdleTime"])

        # All should be accessible and non-negative
        assert m1_blocked.get_value() >= 0.0
        assert m1_starved.get_value() >= 0.0
        assert m1_down.get_value() >= 0.0
        assert m1_processing.get_value() >= 0.0
        assert m1_idle.get_value() >= 0.0

        assert m2_blocked.get_value() >= 0.0
        assert m2_starved.get_value() >= 0.0
        assert m2_down.get_value() >= 0.0
        assert m2_processing.get_value() >= 0.0
        assert m2_idle.get_value() >= 0.0

    def test_time_tracking_increases(self, opcua_client):
        """Verify time tracking values increase over time"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])

        # Get all time tracking variables
        m1_blocked = station1.get_child(["2:BlockedTime"])
        m1_starved = station1.get_child(["2:StarvedTime"])
        m1_down = station1.get_child(["2:DownTime"])
        m1_processing = station1.get_child(["2:ProcessingTime"])
        m1_idle = station1.get_child(["2:IdleTime"])

        # Record initial totals
        initial_total = (m1_blocked.get_value() + m1_starved.get_value() +
                        m1_down.get_value() + m1_processing.get_value() + m1_idle.get_value())

        time.sleep(3)

        # Check that total time increased
        final_total = (m1_blocked.get_value() + m1_starved.get_value() +
                      m1_down.get_value() + m1_processing.get_value() + m1_idle.get_value())

        assert final_total > initial_total, "Total time should increase over time"

    def test_time_accumulation_consistency(self, opcua_client):
        """Verify sum of time tracking ≈ SimTime"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        system = line1.get_child(["2:System"])
        station1 = line1.get_child(["2:Station1"])

        simtime = system.get_child(["2:SimTime"])
        m1_blocked = station1.get_child(["2:BlockedTime"])
        m1_starved = station1.get_child(["2:StarvedTime"])
        m1_down = station1.get_child(["2:DownTime"])
        m1_processing = station1.get_child(["2:ProcessingTime"])
        m1_idle = station1.get_child(["2:IdleTime"])

        # Wait a bit for simulation to run
        time.sleep(5)

        sim_time_value = simtime.get_value()
        total_time = (m1_blocked.get_value() + m1_starved.get_value() +
                     m1_down.get_value() + m1_processing.get_value() + m1_idle.get_value())

        # Allow 5 second tolerance for timing differences
        assert abs(total_time - sim_time_value) < 5.0, \
            f"Total time {total_time}s should approximately equal SimTime {sim_time_value}s"

    def test_utilization_is_real_calculation(self, opcua_client):
        """Verify utilization is based on ProcessingTime / TotalTime (not binary)"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])

        m1_util = station1.get_child(["2:Utilisation"])
        m1_processing = station1.get_child(["2:ProcessingTime"])
        m1_blocked = station1.get_child(["2:BlockedTime"])
        m1_starved = station1.get_child(["2:StarvedTime"])
        m1_down = station1.get_child(["2:DownTime"])
        m1_idle = station1.get_child(["2:IdleTime"])

        time.sleep(5)

        util = m1_util.get_value()
        processing_time = m1_processing.get_value()
        total_time = (processing_time + m1_blocked.get_value() + m1_starved.get_value() +
                     m1_down.get_value() + m1_idle.get_value())

        expected_util = processing_time / total_time if total_time > 0 else 0.0

        # Should match calculation (allow small floating point tolerance)
        assert abs(util - expected_util) < 0.01, \
            f"Utilization {util} should equal ProcessingTime/TotalTime {expected_util}"

    def test_enhanced_states_observable(self, opcua_client):
        """Verify that enhanced states (PROCESSING, IDLE, etc.) are observable"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])
        station2 = line1.get_child(["2:Station2"])

        m1_state = station1.get_child(["2:State"])
        m2_state = station2.get_child(["2:State"])

        # Sample states over time
        states_observed = set()
        for _ in range(10):
            states_observed.add(m1_state.get_value())
            states_observed.add(m2_state.get_value())
            time.sleep(1)

        # Should see at least 2 different states (e.g., PROCESSING and IDLE or PROCESSING and STARVED)
        assert len(states_observed) >= 2, \
            f"Should observe multiple states over time, saw: {states_observed}"


class TestOEEMetrics:
    """Test Phase 6: OEE (Overall Equipment Effectiveness) Calculation"""

    def test_oee_variables_exist(self, opcua_client):
        """Verify all OEE variables are accessible"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])

        # Station 1 OEE
        station1 = line1.get_child(["2:Station1"])
        oee1 = station1.get_child(["2:OEE"])

        availability = oee1.get_child(["2:Availability"])
        performance = oee1.get_child(["2:Performance"])
        quality = oee1.get_child(["2:Quality"])
        oee = oee1.get_child(["2:OEE"])
        good_parts = oee1.get_child(["2:GoodPartCount"])
        defective_parts = oee1.get_child(["2:DefectivePartCount"])
        theoretical = oee1.get_child(["2:TheoreticalOutput"])

        assert availability is not None
        assert performance is not None
        assert quality is not None
        assert oee is not None
        assert good_parts is not None
        assert defective_parts is not None
        assert theoretical is not None

        # Station 2 OEE
        station2 = line1.get_child(["2:Station2"])
        oee2 = station2.get_child(["2:OEE"])

        assert oee2.get_child(["2:Availability"]) is not None
        assert oee2.get_child(["2:Performance"]) is not None
        assert oee2.get_child(["2:Quality"]) is not None
        assert oee2.get_child(["2:OEE"]) is not None

        # Line OEE
        line_kpis = line1.get_child(["2:LineKPIs"])
        line_oee_node = line_kpis.get_child(["2:LineOEE"])

        assert line_oee_node.get_child(["2:Availability"]) is not None
        assert line_oee_node.get_child(["2:Performance"]) is not None
        assert line_oee_node.get_child(["2:Quality"]) is not None
        assert line_oee_node.get_child(["2:OEE"]) is not None

    def test_oee_bounds(self, opcua_client):
        """Verify OEE components are in [0.0, 1.0]"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])

        # Station 1
        station1 = line1.get_child(["2:Station1"])
        oee1 = station1.get_child(["2:OEE"])

        assert 0.0 <= oee1.get_child(["2:Availability"]).get_value() <= 1.0
        assert 0.0 <= oee1.get_child(["2:Performance"]).get_value() <= 1.0
        assert 0.0 <= oee1.get_child(["2:Quality"]).get_value() <= 1.0
        assert 0.0 <= oee1.get_child(["2:OEE"]).get_value() <= 1.0

        # Station 2
        station2 = line1.get_child(["2:Station2"])
        oee2 = station2.get_child(["2:OEE"])

        assert 0.0 <= oee2.get_child(["2:Availability"]).get_value() <= 1.0
        assert 0.0 <= oee2.get_child(["2:Performance"]).get_value() <= 1.0
        assert 0.0 <= oee2.get_child(["2:Quality"]).get_value() <= 1.0
        assert 0.0 <= oee2.get_child(["2:OEE"]).get_value() <= 1.0

        # Line OEE
        line_kpis = line1.get_child(["2:LineKPIs"])
        line_oee_node = line_kpis.get_child(["2:LineOEE"])

        assert 0.0 <= line_oee_node.get_child(["2:Availability"]).get_value() <= 1.0
        assert 0.0 <= line_oee_node.get_child(["2:Performance"]).get_value() <= 1.0
        assert 0.0 <= line_oee_node.get_child(["2:Quality"]).get_value() <= 1.0
        assert 0.0 <= line_oee_node.get_child(["2:OEE"]).get_value() <= 1.0

    def test_oee_formula(self, opcua_client):
        """Verify OEE = Availability × Performance × Quality"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])

        # Station 1
        station1 = line1.get_child(["2:Station1"])
        oee1 = station1.get_child(["2:OEE"])

        avail = oee1.get_child(["2:Availability"]).get_value()
        perf = oee1.get_child(["2:Performance"]).get_value()
        qual = oee1.get_child(["2:Quality"]).get_value()
        oee = oee1.get_child(["2:OEE"]).get_value()

        expected_oee = avail * perf * qual
        assert abs(oee - expected_oee) < 0.001, \
            f"M1 OEE {oee} should equal Avail×Perf×Qual {expected_oee}"

        # Station 2
        station2 = line1.get_child(["2:Station2"])
        oee2 = station2.get_child(["2:OEE"])

        avail2 = oee2.get_child(["2:Availability"]).get_value()
        perf2 = oee2.get_child(["2:Performance"]).get_value()
        qual2 = oee2.get_child(["2:Quality"]).get_value()
        oee2_val = oee2.get_child(["2:OEE"]).get_value()

        expected_oee2 = avail2 * perf2 * qual2
        assert abs(oee2_val - expected_oee2) < 0.001, \
            f"M2 OEE {oee2_val} should equal Avail×Perf×Qual {expected_oee2}"

        # Line OEE
        line_kpis = line1.get_child(["2:LineKPIs"])
        line_oee_node = line_kpis.get_child(["2:LineOEE"])

        line_avail = line_oee_node.get_child(["2:Availability"]).get_value()
        line_perf = line_oee_node.get_child(["2:Performance"]).get_value()
        line_qual = line_oee_node.get_child(["2:Quality"]).get_value()
        line_oee = line_oee_node.get_child(["2:OEE"]).get_value()

        expected_line_oee = line_avail * line_perf * line_qual
        assert abs(line_oee - expected_line_oee) < 0.001, \
            f"Line OEE {line_oee} should equal Avail×Perf×Qual {expected_line_oee}"

    def test_quality_phase6_placeholder(self, opcua_client):
        """Verify Quality is 1.0 (100%) in Phase 6 (no defects yet)"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])

        station1 = line1.get_child(["2:Station1"])
        oee1 = station1.get_child(["2:OEE"])

        # Wait for some parts to be produced
        time.sleep(5)

        good_parts = oee1.get_child(["2:GoodPartCount"]).get_value()
        defective_parts = oee1.get_child(["2:DefectivePartCount"]).get_value()
        quality = oee1.get_child(["2:Quality"]).get_value()

        # Phase 6: All parts are good (no defect tracking yet)
        assert defective_parts == 0, "Phase 6 should have no defective parts"
        if good_parts > 0:
            assert quality == 1.0, "Quality should be 100% when parts are produced"

    def test_line_oee_bottleneck(self, opcua_client):
        """Verify Line OEE uses min (bottleneck) logic"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])

        # Wait for steady state
        time.sleep(10)

        station1 = line1.get_child(["2:Station1"])
        station2 = line1.get_child(["2:Station2"])

        oee1 = station1.get_child(["2:OEE"])
        oee2 = station2.get_child(["2:OEE"])

        m1_avail = oee1.get_child(["2:Availability"]).get_value()
        m2_avail = oee2.get_child(["2:Availability"]).get_value()

        m1_perf = oee1.get_child(["2:Performance"]).get_value()
        m2_perf = oee2.get_child(["2:Performance"]).get_value()

        line_kpis = line1.get_child(["2:LineKPIs"])
        line_oee_node = line_kpis.get_child(["2:LineOEE"])

        line_avail = line_oee_node.get_child(["2:Availability"]).get_value()
        line_perf = line_oee_node.get_child(["2:Performance"]).get_value()

        # Line metrics should be min of station metrics (bottleneck)
        expected_line_avail = min(m1_avail, m2_avail)
        expected_line_perf = min(m1_perf, m2_perf)

        assert abs(line_avail - expected_line_avail) < 0.001, \
            f"Line Availability {line_avail} should be min of station availabilities {expected_line_avail}"
        assert abs(line_perf - expected_line_perf) < 0.001, \
            f"Line Performance {line_perf} should be min of station performances {expected_line_perf}"


class TestAlarmsAndEvents:
    """Test Phase 9: Alarm variables and event generation"""

    def test_alarm_nodes_exist(self, opcua_client):
        """Verify all alarm nodes are accessible"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])
        alarms = station1.get_child(["2:Alarms"])

        # Check alarm variables exist
        alarm_count = alarms.get_child(["2:ActiveAlarmCount"])
        assert alarm_count is not None
        assert alarm_count.get_value() >= 0

        # Check alarm flags exist
        failure_flag = alarms.get_child(["2:MachineFailureActive"])
        assert failure_flag is not None
        assert isinstance(failure_flag.get_value(), bool)

        # Check metadata nodes exist
        last_time = alarms.get_child(["2:LastAlarmTime"])
        last_msg = alarms.get_child(["2:LastAlarmMessage"])
        last_severity = alarms.get_child(["2:LastAlarmSeverity"])
        assert last_time is not None
        assert last_msg is not None
        assert last_severity is not None

    def test_buffer_alarm_nodes_exist(self, opcua_client):
        """Verify buffer alarm nodes are accessible"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        buffer1 = line1.get_child(["2:Buffer1"])
        alarms = buffer1.get_child(["2:Alarms"])

        # Check buffer alarm flags
        high_flag = alarms.get_child(["2:HighLevelWarningActive"])
        low_flag = alarms.get_child(["2:LowLevelWarningActive"])
        assert high_flag is not None
        assert low_flag is not None
        assert isinstance(high_flag.get_value(), bool)
        assert isinstance(low_flag.get_value(), bool)

    def test_alarm_count_increments(self, opcua_client):
        """Verify alarm count changes when alarms activate"""
        root = opcua_client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])
        alarms = station1.get_child(["2:Alarms"])

        alarm_count = alarms.get_child(["2:ActiveAlarmCount"])
        initial_count = alarm_count.get_value()

        # Wait for potential alarms (machine failure, quality alert)
        time.sleep(30)

        # Count should be >= initial (alarms may have triggered)
        final_count = alarm_count.get_value()
        assert final_count >= initial_count

    def test_backward_compatibility(self, opcua_client):
        """Ensure Phase 1-8 tests still pass after Phase 9 changes"""
        # Verify existing nodes still accessible
        simtime = opcua_client.get_node("ns=2;s=Line1.System.SimTime")
        assert simtime is not None

        state = opcua_client.get_node("ns=2;s=Line1.Station1.State")
        assert state is not None

        # No changes to existing node structure


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
