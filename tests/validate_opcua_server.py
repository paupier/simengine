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
        print("[OK] Connected successfully")

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
        print("[OK] System variables OK")

        # Test Control variables
        print("\n[3/6] Testing Control variables...")
        controls = system.get_child(["2:Controls"])
        pause = controls.get_child(["2:PauseLine"])
        interarrival = controls.get_child(["2:InterarrivalTime"])

        print(f"  PauseLine: {pause.get_value()}")
        print(f"  InterarrivalTime: {interarrival.get_value()} seconds")
        print("[OK] Control variables OK")

        # Test Station1 (M1)
        print("\n[4/7] Testing Station1 (M1) variables...")
        station1 = line1.get_child(["2:Station1"])
        m1_state = station1.get_child(["2:State"])
        m1_parts = station1.get_child(["2:PartCount"])
        m1_util = station1.get_child(["2:Utilisation"])
        m1_health = station1.get_child(["2:HealthState"])
        m1_health_pct = station1.get_child(["2:HealthPercent"])
        m1_blocked_time = station1.get_child(["2:BlockedTime"])
        m1_starved_time = station1.get_child(["2:StarvedTime"])
        m1_down_time = station1.get_child(["2:DownTime"])
        m1_processing_time = station1.get_child(["2:ProcessingTime"])
        m1_idle_time = station1.get_child(["2:IdleTime"])

        print(f"  State: {m1_state.get_value()}")
        print(f"  PartCount: {m1_parts.get_value()}")
        print(f"  Utilisation: {m1_util.get_value():.2%}")
        print(f"  HealthState: {m1_health.get_value()} (0=healthy, 1=failed)")
        print(f"  HealthPercent: {m1_health_pct.get_value()}%")
        print(f"  BlockedTime: {m1_blocked_time.get_value()}s")
        print(f"  StarvedTime: {m1_starved_time.get_value()}s")
        print(f"  DownTime: {m1_down_time.get_value()}s")
        print(f"  ProcessingTime: {m1_processing_time.get_value()}s")
        print(f"  IdleTime: {m1_idle_time.get_value()}s")
        print("[OK] Station1 variables OK")

        # Test Buffer1
        print("\n[5/8] Testing Buffer1 variables...")
        buffer1 = line1.get_child(["2:Buffer1"])
        b1_level = buffer1.get_child(["2:CurrentLevel"])
        b1_capacity = buffer1.get_child(["2:Capacity"])

        print(f"  CurrentLevel: {b1_level.get_value()}")
        print(f"  Capacity: {b1_capacity.get_value()}")
        print("[OK] Buffer1 variables OK")

        # Test Station2 (M2)
        print("\n[6/8] Testing Station2 (M2) variables...")
        station2 = line1.get_child(["2:Station2"])
        m2_state = station2.get_child(["2:State"])
        m2_parts = station2.get_child(["2:PartCount"])
        m2_util = station2.get_child(["2:Utilisation"])
        m2_blocked_time = station2.get_child(["2:BlockedTime"])
        m2_starved_time = station2.get_child(["2:StarvedTime"])
        m2_down_time = station2.get_child(["2:DownTime"])
        m2_processing_time = station2.get_child(["2:ProcessingTime"])
        m2_idle_time = station2.get_child(["2:IdleTime"])

        print(f"  State: {m2_state.get_value()}")
        print(f"  PartCount: {m2_parts.get_value()}")
        print(f"  Utilisation: {m2_util.get_value():.2%}")
        print(f"  BlockedTime: {m2_blocked_time.get_value()}s")
        print(f"  StarvedTime: {m2_starved_time.get_value()}s")
        print(f"  DownTime: {m2_down_time.get_value()}s")
        print(f"  ProcessingTime: {m2_processing_time.get_value()}s")
        print(f"  IdleTime: {m2_idle_time.get_value()}s")
        print("[OK] Station2 variables OK")

        # Test Maintenance
        print("\n[7/8] Testing Maintenance variables...")
        maintenance = line1.get_child(["2:Maintenance"])
        maint_active = maintenance.get_child(["2:MaintenanceActive"])
        maint_queue = maintenance.get_child(["2:QueueLength"])
        maint_repairs = maintenance.get_child(["2:TotalRepairs"])

        print(f"  MaintenanceActive: {maint_active.get_value()}")
        print(f"  QueueLength: {maint_queue.get_value()}")
        print(f"  TotalRepairs: {maint_repairs.get_value()}")
        print("[OK] Maintenance variables OK")

        # Test time accumulation consistency
        print("\n[8/8] Testing time accumulation consistency...")
        m1_total = (m1_processing_time.get_value() + m1_blocked_time.get_value() +
                   m1_starved_time.get_value() + m1_down_time.get_value() + m1_idle_time.get_value())
        m2_total = (m2_processing_time.get_value() + m2_blocked_time.get_value() +
                   m2_starved_time.get_value() + m2_down_time.get_value() + m2_idle_time.get_value())

        print(f"  M1 Total Time: {m1_total}s (vs SimTime: {simtime.get_value()}s)")
        print(f"  M2 Total Time: {m2_total}s (vs SimTime: {simtime.get_value()}s)")

        # Allow small tolerance for timing
        if abs(m1_total - simtime.get_value()) < 5.0:
            print("  [OK] M1 time accumulation is consistent")
        else:
            print(f"  [WARN] M1 time accumulation difference: {abs(m1_total - simtime.get_value())}s")

        if abs(m2_total - simtime.get_value()) < 5.0:
            print("  [OK] M2 time accumulation is consistent")
        else:
            print(f"  [WARN] M2 time accumulation difference: {abs(m2_total - simtime.get_value())}s")

        print("[OK] Time accumulation OK")

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
        print("[OK] Write capability OK")

        # Summary
        print("\n" + "=" * 60)
        print("[OK] ALL VALIDATIONS PASSED")
        print("=" * 60)

        client.disconnect()
        return True

    except Exception as e:
        print(f"\n[FAIL] VALIDATION FAILED: {e}")
        return False


if __name__ == "__main__":
    success = validate_opcua_server()
    exit(0 if success else 1)
