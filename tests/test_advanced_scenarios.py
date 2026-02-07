"""
Integration Tests for Advanced Failure Modes (Phase 10c)

Tests OPC UA server integration with AdvancedMachine and failure modes.
"""
import pytest
import time
from opcua import Client


class TestAdvancedFailureScenario:
    """Test advanced_failure_line scenario integration."""

    @pytest.fixture(scope="class")
    def opcua_client_advanced(self):
        """Start server with advanced_failure_line and connect client."""
        import threading
        from src.opcua_server import main

        # Start server in background thread with advanced scenario
        server_thread = threading.Thread(
            target=lambda: main(["--scenario", "advanced_failure_line"]),
            daemon=True
        )
        server_thread.start()

        # Wait for server to initialize
        time.sleep(3)

        # Connect client
        client = Client("opc.tcp://localhost:4840/simantha/")
        client.connect()

        yield client

        client.disconnect()

    def test_advanced_server_starts(self, opcua_client_advanced):
        """Server starts successfully with advanced_failure_line scenario."""
        # If we get here, server started and client connected
        assert opcua_client_advanced is not None

    def test_failure_mode_variables_exist(self, opcua_client_advanced):
        """FailureModes OPC UA nodes exist for Station1."""
        root = opcua_client_advanced.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])

        # Should have FailureModes node
        fm_node = station1.get_child(["2:FailureModes"])
        assert fm_node is not None

        # Should have ActiveFailureMode variable
        active_mode = fm_node.get_child(["2:ActiveFailureMode"])
        assert active_mode is not None
        active_value = active_mode.get_value()
        assert isinstance(active_value, str)

        # Should have MechanicalFailureCount (from advanced_failure_line config)
        mech_count = fm_node.get_child(["2:MechanicalFailureCount"])
        assert mech_count is not None
        count_value = mech_count.get_value()
        assert isinstance(count_value, int)
        assert count_value >= 0

        # Should have MechanicalMTBF
        mech_mtbf = fm_node.get_child(["2:MechanicalMTBF"])
        assert mech_mtbf is not None
        mtbf_value = mech_mtbf.get_value()
        assert isinstance(mtbf_value, float)
        assert mtbf_value >= 0.0

    def test_maintenance_strategy_variables_exist(self, opcua_client_advanced):
        """MaintenanceStrategy OPC UA nodes exist for Station1."""
        root = opcua_client_advanced.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])

        # Should have MaintenanceStrategy node
        ms_node = station1.get_child(["2:MaintenanceStrategy"])
        assert ms_node is not None

        # Should have StrategyType variable
        strategy_type = ms_node.get_child(["2:StrategyType"])
        assert strategy_type is not None
        type_value = strategy_type.get_value()
        assert type_value in ["corrective", "preventive", "predictive"]

        # Should have CMCount (corrective maintenance count)
        cm_count = ms_node.get_child(["2:CMCount"])
        assert cm_count is not None
        cm_value = cm_count.get_value()
        assert isinstance(cm_value, int)
        assert cm_value >= 0

    def test_electrical_failure_mode_exists(self, opcua_client_advanced):
        """ElectricalFailureCount exists (second failure mode from config)."""
        root = opcua_client_advanced.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])
        fm_node = station1.get_child(["2:FailureModes"])

        # Should have ElectricalFailureCount
        elec_count = fm_node.get_child(["2:ElectricalFailureCount"])
        assert elec_count is not None
        count_value = elec_count.get_value()
        assert isinstance(count_value, int)

    def test_station2_no_failure_modes(self, opcua_client_advanced):
        """Station2 (M2) has no FailureModes node (not configured in advanced_failure_line)."""
        root = opcua_client_advanced.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station2 = line1.get_child(["2:Station2"])

        # Attempt to get FailureModes node - should raise exception
        with pytest.raises(Exception):  # OPC UA raises BadNoMatch or similar
            fm_node = station2.get_child(["2:FailureModes"])


class TestBackwardCompatibility:
    """Test that legacy scenarios still work with Phase 10 changes."""

    @pytest.fixture(scope="class")
    def opcua_client_legacy(self):
        """Start server with failure_line (Phase 4 scenario) and connect client."""
        import threading
        from src.opcua_server import main

        # Start server in background thread with legacy scenario
        server_thread = threading.Thread(
            target=lambda: main(["--scenario", "failure_line"]),
            daemon=True
        )
        server_thread.start()

        # Wait for server to initialize
        time.sleep(3)

        # Connect client
        client = Client("opc.tcp://localhost:4840/simantha/")
        client.connect()

        yield client

        client.disconnect()

    def test_legacy_server_starts(self, opcua_client_legacy):
        """Server starts successfully with legacy failure_line scenario."""
        assert opcua_client_legacy is not None

    def test_legacy_health_variables_still_work(self, opcua_client_legacy):
        """Legacy health variables (Phase 4) still exist and work."""
        root = opcua_client_legacy.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])

        # Should have health variables (enable_degradation=true in failure_line)
        health_state = station1.get_child(["2:HealthState"])
        assert health_state is not None
        health_value = health_state.get_value()
        assert isinstance(health_value, int)
        assert health_value in [0, 1]  # 0=healthy, 1=failed

    def test_legacy_no_failure_modes(self, opcua_client_legacy):
        """Legacy scenarios don't have FailureModes nodes."""
        root = opcua_client_legacy.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])

        # Attempt to get FailureModes node - should raise exception
        with pytest.raises(Exception):  # OPC UA raises BadNoMatch or similar
            fm_node = station1.get_child(["2:FailureModes"])

    def test_legacy_all_standard_variables_exist(self, opcua_client_legacy):
        """All standard Phase 1-9 variables still exist in legacy scenarios."""
        root = opcua_client_legacy.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        station1 = line1.get_child(["2:Station1"])

        # Phase 1 variables
        state = station1.get_child(["2:State"])
        assert state is not None

        partcount = station1.get_child(["2:PartCount"])
        assert partcount is not None

        # Phase 5 time variables
        blocked_time = station1.get_child(["2:BlockedTime"])
        assert blocked_time is not None

        # Phase 6 OEE
        oee_node = station1.get_child(["2:OEE"])
        assert oee_node is not None
        oee_value = oee_node.get_child(["2:OEE"])
        assert oee_value is not None

        # Phase 9 Alarms
        alarms_node = station1.get_child(["2:Alarms"])
        assert alarms_node is not None
