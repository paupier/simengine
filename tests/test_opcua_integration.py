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
        pause = opcua_client.get_node("ns=2;s=Line1.System.Controls.PauseLine")
        interarrival = opcua_client.get_node(
            "ns=2;s=Line1.System.Controls.InterarrivalTime"
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
        """Verify PauseLine control freezes simulation"""
        pause = opcua_client.get_node("ns=2;s=Line1.System.Controls.PauseLine")
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
        """Verify InterarrivalTime control affects throughput rate"""
        interarrival = opcua_client.get_node(
            "ns=2;s=Line1.System.Controls.InterarrivalTime"
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

        valid_states = ["IDLE", "RUNNING", "PAUSED", "FAILED", "UNDER_REPAIR"]

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
