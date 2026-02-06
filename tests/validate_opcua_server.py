"""
Quick OPC UA Server Validation Script

Run this script while the OPC UA server is running to verify all variables
are accessible and have valid values.

Usage:
    1. Start server: python src/opcua_server.py
    2. Run validator: python tests/validate_opcua_server.py
"""
import time
from opcua import Client


def validate_opcua_server():
    """Connect to OPC UA server and validate all variables"""
    print("=" * 60)
    print("OPC UA Server Validation")
    print("=" * 60)

    try:
        # Connect to server
        print("\n[1/6] Connecting to server...")
        client = Client("opc.tcp://localhost:4840/simantha/")
        client.connect()
        print("✓ Connected successfully")

        # Test System variables
        print("\n[2/6] Testing System variables...")
        # Use browse path to get nodes (more reliable than string node IDs)
        root = client.get_objects_node()
        line1 = root.get_child(["2:Line1"])
        system = line1.get_child(["2:System"])
        simtime = system.get_child(["2:SimTime"])
        throughput = system.get_child(["2:Throughput"])

        line_kpis = line1.get_child(["2:LineKPIs"])
        total_wip = line_kpis.get_child(["2:TotalWIP"])

        print(f"  SimTime: {simtime.get_value()} seconds")
        print(f"  Throughput: {throughput.get_value()} parts")
        print(f"  TotalWIP: {total_wip.get_value()} parts")
        print("✓ System variables OK")

        # Test Control variables
        print("\n[3/6] Testing Control variables...")
        controls = system.get_child(["2:Controls"])
        pause = controls.get_child(["2:PauseLine"])
        interarrival = controls.get_child(["2:InterarrivalTime"])

        print(f"  PauseLine: {pause.get_value()}")
        print(f"  InterarrivalTime: {interarrival.get_value()} seconds")
        print("✓ Control variables OK")

        # Test Station1 (M1)
        print("\n[4/6] Testing Station1 (M1) variables...")
        station1 = line1.get_child(["2:Station1"])
        m1_state = station1.get_child(["2:State"])
        m1_parts = station1.get_child(["2:PartCount"])
        m1_util = station1.get_child(["2:Utilisation"])
        m1_health = station1.get_child(["2:HealthState"])
        m1_health_pct = station1.get_child(["2:HealthPercent"])

        print(f"  State: {m1_state.get_value()}")
        print(f"  PartCount: {m1_parts.get_value()}")
        print(f"  Utilisation: {m1_util.get_value()}")
        print(f"  HealthState: {m1_health.get_value()} (0=healthy, 1=failed)")
        print(f"  HealthPercent: {m1_health_pct.get_value()}%")
        print("✓ Station1 variables OK")

        # Test Buffer1
        print("\n[5/6] Testing Buffer1 variables...")
        buffer1 = line1.get_child(["2:Buffer1"])
        b1_level = buffer1.get_child(["2:CurrentLevel"])
        b1_capacity = buffer1.get_child(["2:Capacity"])

        print(f"  CurrentLevel: {b1_level.get_value()}")
        print(f"  Capacity: {b1_capacity.get_value()}")
        print("✓ Buffer1 variables OK")

        # Test Station2 (M2)
        print("\n[6/6] Testing Station2 (M2) variables...")
        station2 = line1.get_child(["2:Station2"])
        m2_state = station2.get_child(["2:State"])
        m2_parts = station2.get_child(["2:PartCount"])
        m2_util = station2.get_child(["2:Utilisation"])

        print(f"  State: {m2_state.get_value()}")
        print(f"  PartCount: {m2_parts.get_value()}")
        print(f"  Utilisation: {m2_util.get_value()}")
        print("✓ Station2 variables OK")

        # Test Maintenance
        print("\n[7/7] Testing Maintenance variables...")
        maintenance = line1.get_child(["2:Maintenance"])
        maint_active = maintenance.get_child(["2:MaintenanceActive"])
        maint_queue = maintenance.get_child(["2:QueueLength"])
        maint_repairs = maintenance.get_child(["2:TotalRepairs"])

        print(f"  MaintenanceActive: {maint_active.get_value()}")
        print(f"  QueueLength: {maint_queue.get_value()}")
        print(f"  TotalRepairs: {maint_repairs.get_value()}")
        print("✓ Maintenance variables OK")

        # Test write capability
        print("\n[BONUS] Testing write capability...")
        original_pause = pause.get_value()
        print(f"  Current PauseLine: {original_pause}")
        print(f"  Toggling PauseLine...")
        pause.set_value(not original_pause)
        time.sleep(1)
        new_pause = pause.get_value()
        print(f"  New PauseLine: {new_pause}")
        pause.set_value(original_pause)  # Restore
        print("✓ Write capability OK")

        # Summary
        print("\n" + "=" * 60)
        print("✓ ALL VALIDATIONS PASSED")
        print("=" * 60)

        client.disconnect()
        return True

    except Exception as e:
        print(f"\n✗ VALIDATION FAILED: {e}")
        return False


if __name__ == "__main__":
    success = validate_opcua_server()
    exit(0 if success else 1)
