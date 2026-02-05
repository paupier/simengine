import time

from opcua import Server
from simantha import Source, Machine, Buffer, Sink, System, Maintainer


# Machine health degradation matrix (2-state: healthy → failed)
# State 0: healthy, State 1: failed (absorbing until maintenance)
DEGRADATION_MATRIX = [
    [0.99, 0.01],  # from healthy: 99% stay healthy, 1% degrade per step
    [0.0, 1.0],    # from failed: stay failed until maintainer repairs
]


def build_simantha_system(enable_degradation=True):
    """
    Build a 2-machine serial line with optional health degradation on M1.

    Args:
        enable_degradation: If True, M1 will degrade over time and require maintenance

    Returns:
        tuple: (system, source, sink, b1, m1, m2, maintainer)
    """
    source = Source()

    # M1 with optional degradation modeling
    if enable_degradation:
        m1 = Machine(
            name="M1",
            cycle_time=1,
            degradation_matrix=DEGRADATION_MATRIX,
            cbm_threshold=1,  # request maintenance when state=1 (failed)
        )
        maintainer = Maintainer(capacity=1)
    else:
        m1 = Machine(name="M1", cycle_time=1)
        maintainer = None

    b1 = Buffer(name="B1", capacity=10)
    m2 = Machine(name="M2", cycle_time=1)
    sink = Sink(collect_parts=True)

    # Routing
    source.define_routing(downstream=[m1])
    m1.define_routing(upstream=[source], downstream=[b1])
    b1.define_routing(upstream=[m1], downstream=[m2])
    m2.define_routing(upstream=[b1], downstream=[sink])

    # System with optional maintainer
    if maintainer is not None:
        system = System(objects=[source, m1, b1, m2, sink], maintainer=maintainer)
    else:
        system = System(objects=[source, m1, b1, m2, sink])

    return system, source, sink, b1, m1, m2, maintainer


def build_opcua_server():
    server = Server()
    server.set_endpoint("opc.tcp://0.0.0.0:4840/simantha/")

    uri = "http://simantha.nist.gov/"
    idx = server.register_namespace(uri)

    objects = server.get_objects_node()

    # Top-level line object
    line1 = objects.add_object(idx, "Line1")

    # System / KPIs under the line
    system_node = line1.add_object(idx, "System")
    var_simtime = system_node.add_variable(idx, "SimTime", 0.0)
    var_throughput = system_node.add_variable(idx, "Throughput", 0)

    # Line-level KPIs
    line_kpi_node = line1.add_object(idx, "LineKPIs")
    var_total_wip = line_kpi_node.add_variable(idx, "TotalWIP", 0)

    # System controls (writable inputs to control simulation)
    controls_node = system_node.add_object(idx, "Controls")
    var_pause_line = controls_node.add_variable(idx, "PauseLine", False)
    var_interarrival = controls_node.add_variable(idx, "InterarrivalTime", 0.0)

    # Station 1 (M1) with health/maintenance tracking
    station1_node = line1.add_object(idx, "Station1")
    var_m1_state = station1_node.add_variable(idx, "State", "IDLE")
    var_m1_partcount = station1_node.add_variable(idx, "PartCount", 0)
    var_m1_util = station1_node.add_variable(idx, "Utilisation", 0.0)
    var_m1_health = station1_node.add_variable(idx, "HealthState", 0)  # 0=healthy, 1=failed
    var_m1_health_pct = station1_node.add_variable(idx, "HealthPercent", 100.0)  # 100=healthy, 0=failed

    # Buffer between Station1 and Station2
    buffer1_node = line1.add_object(idx, "Buffer1")
    var_b1_level = buffer1_node.add_variable(idx, "CurrentLevel", 0)
    var_b1_capacity = buffer1_node.add_variable(idx, "Capacity", 10)

    # Station 2 (M2)
    station2_node = line1.add_object(idx, "Station2")
    var_m2_state = station2_node.add_variable(idx, "State", "IDLE")
    var_m2_partcount = station2_node.add_variable(idx, "PartCount", 0)
    var_m2_util = station2_node.add_variable(idx, "Utilisation", 0.0)

    # Maintenance/Degradation (only applicable if degradation enabled)
    maintenance_node = line1.add_object(idx, "Maintenance")
    var_maint_active = maintenance_node.add_variable(idx, "MaintenanceActive", False)
    var_maint_queue = maintenance_node.add_variable(idx, "QueueLength", 0)
    var_total_repairs = maintenance_node.add_variable(idx, "TotalRepairs", 0)

    # Separate read-only (outputs/KPIs) from writable (inputs/controls)

    # READ-ONLY: Simulation outputs and KPIs (clients can only monitor)
    # Note: List for documentation; OPC UA variables are read-only by default
    readonly_vars = [
        var_simtime,        # System/SimTime
        var_throughput,     # System/Throughput
        var_total_wip,      # LineKPIs/TotalWIP
        var_m1_state,       # Station1/State
        var_m1_partcount,   # Station1/PartCount
        var_m1_util,        # Station1/Utilisation
        var_m1_health,      # Station1/HealthState
        var_m1_health_pct,  # Station1/HealthPercent
        var_b1_level,       # Buffer1/CurrentLevel
        var_b1_capacity,    # Buffer1/Capacity
        var_m2_state,       # Station2/State
        var_m2_partcount,   # Station2/PartCount
        var_m2_util,        # Station2/Utilisation
        var_maint_active,   # Maintenance/MaintenanceActive
        var_maint_queue,    # Maintenance/QueueLength
        var_total_repairs,  # Maintenance/TotalRepairs
    ]
    # Read-only variables are not explicitly set (default is read-only in OPC UA)

    # WRITABLE: Control inputs (clients can change these to control the simulation)
    writable_vars = [
        var_pause_line,     # System/Controls/PauseLine
        var_interarrival,   # System/Controls/InterarrivalTime
    ]
    for v in writable_vars:
        v.set_writable()

    variables = {
        # System KPIs (read-only)
        "simtime": var_simtime,
        "throughput": var_throughput,
        "total_wip": var_total_wip,
        # System Controls (writable)
        "pause_line": var_pause_line,
        "interarrival_time": var_interarrival,
        # Station 1 (M1) - read-only
        "m1_state": var_m1_state,
        "m1_partcount": var_m1_partcount,
        "m1_utilisation": var_m1_util,
        "m1_health": var_m1_health,
        "m1_health_pct": var_m1_health_pct,
        # Buffer 1 - read-only
        "b1_level": var_b1_level,
        "b1_capacity": var_b1_capacity,
        # Station 2 (M2) - read-only
        "m2_state": var_m2_state,
        "m2_partcount": var_m2_partcount,
        "m2_utilisation": var_m2_util,
        # Maintenance - read-only
        "maint_active": var_maint_active,
        "maint_queue": var_maint_queue,
        "total_repairs": var_total_repairs,
    }

    return server, variables, idx


def main():
    # Build system with degradation enabled (set to False for simple mode)
    system, source, sink, b1, m1, m2, maintainer = build_simantha_system(enable_degradation=True)

    server, vars_, idx = build_opcua_server()

    sim_time = 0.0
    sim_step = 1.0
    real_step = 1.0

    # Manual part counters (only increase, never decrease)
    prev_sink_level = 0
    total_parts_produced = 0

    server.start()
    print("OPC UA server started at opc.tcp://localhost:4840/simantha/")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            # --- Read controls from OPC UA ---
            pause_line = bool(vars_["pause_line"].get_value())
            interarrival = float(vars_["interarrival_time"].get_value())

            # Push interarrival time into Simantha source
            # 0.0 means "never starved" per Simantha docs; >0 slows arrivals.
            source.interarrival_time = interarrival

            # --- Stepping: same pattern as before ---
            if not pause_line:
                # Advance simulation only when not paused
                sim_time += sim_step
                system.simulate(simulation_time=sim_time)

            # --- Compute metrics using Simantha ---
            current_sim_time = sim_time

            # Throughput: track parts produced with monotonic counter
            # (sink.level can decrease during maintenance, so we track increases only)
            current_sink_level = sink.level
            if current_sink_level > prev_sink_level:
                # Parts increased - add delta to total
                delta_parts = current_sink_level - prev_sink_level
                total_parts_produced += delta_parts
                prev_sink_level = current_sink_level
            elif current_sink_level < prev_sink_level:
                # Sink level decreased (maintenance reset?) - resync but don't lose count
                # Keep total_parts_produced as-is, just update prev_sink_level
                prev_sink_level = current_sink_level

            current_throughput = total_parts_produced

            # Station part counts (same for series line)
            m1_partcount = total_parts_produced
            m2_partcount = total_parts_produced

            # Buffer WIP from B1
            try:
                b1_level = b1.level  # or len(b1.contents)[web:17]
            except AttributeError:
                b1_level = 0

            b1_capacity = b1.capacity
            total_wip = b1_level

            # Machine health (if degradation enabled)
            try:
                m1_health_state = m1.health  # 0=healthy, 1=failed
                # Convert to percentage (0=failed, 100=healthy)
                m1_health_percent = 100.0 * (1 - m1_health_state)
            except AttributeError:
                # No degradation model
                m1_health_state = 0
                m1_health_percent = 100.0

            # Maintenance status (if maintainer exists)
            if maintainer is not None:
                try:
                    # Check if maintainer is currently repairing
                    maint_active = len(maintainer.in_progress) > 0
                    # Queue length (machines waiting for maintenance)
                    maint_queue_length = len(maintainer.queue)
                    # Total repairs completed (rough estimate from maintainer stats)
                    total_repairs = maintainer.total_throughput if hasattr(maintainer, 'total_throughput') else 0
                except AttributeError:
                    maint_active = False
                    maint_queue_length = 0
                    total_repairs = 0
            else:
                maint_active = False
                maint_queue_length = 0
                total_repairs = 0

            # Utilisation and state (global pause + health status)
            if pause_line:
                # Global pause: entire line paused
                m1_utilisation = 0.0
                m2_utilisation = 0.0
                m1_state = "PAUSED"
                m2_state = "PAUSED"
            else:
                # M1 state considers health status
                if m1_health_state == 1:  # Failed
                    m1_utilisation = 0.0
                    m1_state = "FAILED" if not maint_active else "UNDER_REPAIR"
                else:  # Healthy
                    m1_utilisation = 1.0
                    m1_state = "RUNNING"

                # M2 state (no degradation modeling on M2)
                m2_utilisation = 1.0
                m2_state = "RUNNING"

            # --- Write KPIs back to OPC UA ---
            vars_["simtime"].set_value(current_sim_time)
            vars_["throughput"].set_value(current_throughput)
            vars_["total_wip"].set_value(total_wip)

            vars_["m1_partcount"].set_value(m1_partcount)
            vars_["m1_state"].set_value(m1_state)
            vars_["m1_utilisation"].set_value(m1_utilisation)
            vars_["m1_health"].set_value(m1_health_state)
            vars_["m1_health_pct"].set_value(m1_health_percent)

            vars_["b1_level"].set_value(b1_level)
            vars_["b1_capacity"].set_value(b1_capacity)

            vars_["m2_partcount"].set_value(m2_partcount)
            vars_["m2_state"].set_value(m2_state)
            vars_["m2_utilisation"].set_value(m2_utilisation)

            vars_["maint_active"].set_value(maint_active)
            vars_["maint_queue"].set_value(maint_queue_length)
            vars_["total_repairs"].set_value(total_repairs)

            time.sleep(real_step)

    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        server.stop()
        print("Server stopped.")



if __name__ == "__main__":
    main()