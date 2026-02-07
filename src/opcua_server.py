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

    # Line-level OEE (Phase 6)
    line_oee_node = line_kpi_node.add_object(idx, "LineOEE")
    var_line_availability = line_oee_node.add_variable(idx, "Availability", 0.0)
    var_line_performance = line_oee_node.add_variable(idx, "Performance", 0.0)
    var_line_quality = line_oee_node.add_variable(idx, "Quality", 1.0)
    var_line_oee = line_oee_node.add_variable(idx, "OEE", 0.0)

    # System controls (writable inputs to control simulation)
    controls_node = system_node.add_object(idx, "Controls")
    var_pause_line = controls_node.add_variable(idx, "cmdPauseLine", False)
    var_interarrival = controls_node.add_variable(idx, "setInterarrivalTime", 0.0)

    # Station 1 (M1) with health/maintenance tracking
    station1_node = line1.add_object(idx, "Station1")
    var_m1_state = station1_node.add_variable(idx, "State", "IDLE")
    var_m1_partcount = station1_node.add_variable(idx, "PartCount", 0)
    var_m1_util = station1_node.add_variable(idx, "Utilisation", 0.0)
    var_m1_health = station1_node.add_variable(idx, "HealthState", 0)  # 0=healthy, 1=failed
    var_m1_health_pct = station1_node.add_variable(idx, "HealthPercent", 100.0)  # 100=healthy, 0=failed
    # Time tracking variables
    var_m1_blocked_time = station1_node.add_variable(idx, "BlockedTime", 0.0)
    var_m1_starved_time = station1_node.add_variable(idx, "StarvedTime", 0.0)
    var_m1_down_time = station1_node.add_variable(idx, "DownTime", 0.0)
    var_m1_processing_time = station1_node.add_variable(idx, "ProcessingTime", 0.0)
    var_m1_idle_time = station1_node.add_variable(idx, "IdleTime", 0.0)

    # OEE Metrics (Phase 6)
    oee1_node = station1_node.add_object(idx, "OEE")
    var_m1_availability = oee1_node.add_variable(idx, "Availability", 0.0)
    var_m1_performance = oee1_node.add_variable(idx, "Performance", 0.0)
    var_m1_quality = oee1_node.add_variable(idx, "Quality", 1.0)
    var_m1_oee = oee1_node.add_variable(idx, "OEE", 0.0)
    var_m1_good_parts = oee1_node.add_variable(idx, "GoodPartCount", 0)
    var_m1_defective_parts = oee1_node.add_variable(idx, "DefectivePartCount", 0)
    var_m1_theoretical = oee1_node.add_variable(idx, "TheoreticalOutput", 0.0)

    # Buffer between Station1 and Station2
    buffer1_node = line1.add_object(idx, "Buffer1")
    var_b1_level = buffer1_node.add_variable(idx, "CurrentLevel", 0)
    var_b1_capacity = buffer1_node.add_variable(idx, "Capacity", 10)

    # Station 2 (M2)
    station2_node = line1.add_object(idx, "Station2")
    var_m2_state = station2_node.add_variable(idx, "State", "IDLE")
    var_m2_partcount = station2_node.add_variable(idx, "PartCount", 0)
    var_m2_util = station2_node.add_variable(idx, "Utilisation", 0.0)
    # Time tracking variables
    var_m2_blocked_time = station2_node.add_variable(idx, "BlockedTime", 0.0)
    var_m2_starved_time = station2_node.add_variable(idx, "StarvedTime", 0.0)
    var_m2_down_time = station2_node.add_variable(idx, "DownTime", 0.0)
    var_m2_processing_time = station2_node.add_variable(idx, "ProcessingTime", 0.0)
    var_m2_idle_time = station2_node.add_variable(idx, "IdleTime", 0.0)

    # OEE Metrics (Phase 6)
    oee2_node = station2_node.add_object(idx, "OEE")
    var_m2_availability = oee2_node.add_variable(idx, "Availability", 0.0)
    var_m2_performance = oee2_node.add_variable(idx, "Performance", 0.0)
    var_m2_quality = oee2_node.add_variable(idx, "Quality", 1.0)
    var_m2_oee = oee2_node.add_variable(idx, "OEE", 0.0)
    var_m2_good_parts = oee2_node.add_variable(idx, "GoodPartCount", 0)
    var_m2_defective_parts = oee2_node.add_variable(idx, "DefectivePartCount", 0)
    var_m2_theoretical = oee2_node.add_variable(idx, "TheoreticalOutput", 0.0)

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
        var_line_availability,  # LineKPIs/LineOEE/Availability
        var_line_performance,   # LineKPIs/LineOEE/Performance
        var_line_quality,       # LineKPIs/LineOEE/Quality
        var_line_oee,           # LineKPIs/LineOEE/OEE
        var_m1_state,       # Station1/State
        var_m1_partcount,   # Station1/PartCount
        var_m1_util,        # Station1/Utilisation
        var_m1_health,      # Station1/HealthState
        var_m1_health_pct,  # Station1/HealthPercent
        var_m1_blocked_time,    # Station1/BlockedTime
        var_m1_starved_time,    # Station1/StarvedTime
        var_m1_down_time,       # Station1/DownTime
        var_m1_processing_time, # Station1/ProcessingTime
        var_m1_idle_time,       # Station1/IdleTime
        var_m1_availability,    # Station1/OEE/Availability
        var_m1_performance,     # Station1/OEE/Performance
        var_m1_quality,         # Station1/OEE/Quality
        var_m1_oee,             # Station1/OEE/OEE
        var_m1_good_parts,      # Station1/OEE/GoodPartCount
        var_m1_defective_parts, # Station1/OEE/DefectivePartCount
        var_m1_theoretical,     # Station1/OEE/TheoreticalOutput
        var_b1_level,       # Buffer1/CurrentLevel
        var_b1_capacity,    # Buffer1/Capacity
        var_m2_state,       # Station2/State
        var_m2_partcount,   # Station2/PartCount
        var_m2_util,        # Station2/Utilisation
        var_m2_blocked_time,    # Station2/BlockedTime
        var_m2_starved_time,    # Station2/StarvedTime
        var_m2_down_time,       # Station2/DownTime
        var_m2_processing_time, # Station2/ProcessingTime
        var_m2_idle_time,       # Station2/IdleTime
        var_m2_availability,    # Station2/OEE/Availability
        var_m2_performance,     # Station2/OEE/Performance
        var_m2_quality,         # Station2/OEE/Quality
        var_m2_oee,             # Station2/OEE/OEE
        var_m2_good_parts,      # Station2/OEE/GoodPartCount
        var_m2_defective_parts, # Station2/OEE/DefectivePartCount
        var_m2_theoretical,     # Station2/OEE/TheoreticalOutput
        var_maint_active,   # Maintenance/MaintenanceActive
        var_maint_queue,    # Maintenance/QueueLength
        var_total_repairs,  # Maintenance/TotalRepairs
    ]
    # Read-only variables are not explicitly set (default is read-only in OPC UA)

    # WRITABLE: Control inputs (clients can change these to control the simulation)
    writable_vars = [
        var_pause_line,     # System/Controls/cmdPauseLine
        var_interarrival,   # System/Controls/setInterarrivalTime
    ]
    for v in writable_vars:
        v.set_writable()

    variables = {
        # System KPIs (read-only)
        "simtime": var_simtime,
        "throughput": var_throughput,
        "total_wip": var_total_wip,
        # Line OEE - read-only
        "line_availability": var_line_availability,
        "line_performance": var_line_performance,
        "line_quality": var_line_quality,
        "line_oee": var_line_oee,
        # System Controls (writable)
        "pause_line": var_pause_line,
        "interarrival_time": var_interarrival,
        # Station 1 (M1) - read-only
        "m1_state": var_m1_state,
        "m1_partcount": var_m1_partcount,
        "m1_utilisation": var_m1_util,
        "m1_health": var_m1_health,
        "m1_health_pct": var_m1_health_pct,
        "m1_blocked_time": var_m1_blocked_time,
        "m1_starved_time": var_m1_starved_time,
        "m1_down_time": var_m1_down_time,
        "m1_processing_time": var_m1_processing_time,
        "m1_idle_time": var_m1_idle_time,
        # Station 1 OEE - read-only
        "m1_availability": var_m1_availability,
        "m1_performance": var_m1_performance,
        "m1_quality": var_m1_quality,
        "m1_oee": var_m1_oee,
        "m1_good_parts": var_m1_good_parts,
        "m1_defective_parts": var_m1_defective_parts,
        "m1_theoretical": var_m1_theoretical,
        # Buffer 1 - read-only
        "b1_level": var_b1_level,
        "b1_capacity": var_b1_capacity,
        # Station 2 (M2) - read-only
        "m2_state": var_m2_state,
        "m2_partcount": var_m2_partcount,
        "m2_utilisation": var_m2_util,
        "m2_blocked_time": var_m2_blocked_time,
        "m2_starved_time": var_m2_starved_time,
        "m2_down_time": var_m2_down_time,
        "m2_processing_time": var_m2_processing_time,
        "m2_idle_time": var_m2_idle_time,
        # Station 2 OEE - read-only
        "m2_availability": var_m2_availability,
        "m2_performance": var_m2_performance,
        "m2_quality": var_m2_quality,
        "m2_oee": var_m2_oee,
        "m2_good_parts": var_m2_good_parts,
        "m2_defective_parts": var_m2_defective_parts,
        "m2_theoretical": var_m2_theoretical,
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

    # Nominal cycle times (fixed values, not Distribution objects)
    m1_nominal_cycle_time = 1.0  # seconds
    m2_nominal_cycle_time = 1.0  # seconds

    # Manual part counters (only increase, never decrease)
    prev_sink_level = 0
    total_parts_produced = 0

    # Per-station time tracking counters
    m1_blocked_time = 0.0
    m1_starved_time = 0.0
    m1_down_time = 0.0
    m1_processing_time = 0.0
    m1_idle_time = 0.0
    prev_m1_state = "IDLE"

    m2_blocked_time = 0.0
    m2_starved_time = 0.0
    m2_down_time = 0.0
    m2_processing_time = 0.0
    m2_idle_time = 0.0
    prev_m2_state = "IDLE"

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

            # Accumulate time based on previous state (before determining new state)
            if not pause_line:
                # Only accumulate when simulation is running
                # M1 time accumulation
                if prev_m1_state == "BLOCKED":
                    m1_blocked_time += sim_step
                elif prev_m1_state == "STARVED":
                    m1_starved_time += sim_step
                elif prev_m1_state == "FAILED" or prev_m1_state == "UNDER_REPAIR":
                    m1_down_time += sim_step
                elif prev_m1_state == "PROCESSING":
                    m1_processing_time += sim_step
                elif prev_m1_state == "IDLE":
                    m1_idle_time += sim_step

                # M2 time accumulation
                if prev_m2_state == "BLOCKED":
                    m2_blocked_time += sim_step
                elif prev_m2_state == "STARVED":
                    m2_starved_time += sim_step
                elif prev_m2_state == "FAILED" or prev_m2_state == "UNDER_REPAIR":
                    m2_down_time += sim_step
                elif prev_m2_state == "PROCESSING":
                    m2_processing_time += sim_step
                elif prev_m2_state == "IDLE":
                    m2_idle_time += sim_step

            # Enhanced state detection using Simantha's built-in flags
            if pause_line:
                # Global pause: entire line paused
                m1_state = "PAUSED"
                m2_state = "PAUSED"
            else:
                # M1 state: check health first, then Simantha state flags
                if m1_health_state == 1:  # Failed
                    m1_state = "FAILED" if not maint_active else "UNDER_REPAIR"
                elif m1.blocked:  # Waiting for downstream buffer space
                    m1_state = "BLOCKED"
                elif m1.starved:  # Waiting for upstream parts
                    m1_state = "STARVED"
                elif m1.has_part:  # Actively processing a part
                    m1_state = "PROCESSING"
                else:
                    m1_state = "IDLE"  # Waiting for work

                # M2 state: same logic but no health degradation
                if m2.blocked:  # Waiting for downstream (sink never blocks, but check anyway)
                    m2_state = "BLOCKED"
                elif m2.starved:  # Waiting for upstream parts from buffer
                    m2_state = "STARVED"
                elif m2.has_part:  # Actively processing a part
                    m2_state = "PROCESSING"
                else:
                    m2_state = "IDLE"  # Waiting for work

            # Calculate real utilization based on time tracking
            # Utilization = ProcessingTime / TotalTime (time actually making parts)
            m1_total_time = m1_processing_time + m1_blocked_time + m1_starved_time + m1_down_time + m1_idle_time
            m1_utilisation = m1_processing_time / m1_total_time if m1_total_time > 0 else 0.0

            m2_total_time = m2_processing_time + m2_blocked_time + m2_starved_time + m2_down_time + m2_idle_time
            m2_utilisation = m2_processing_time / m2_total_time if m2_total_time > 0 else 0.0

            # Update previous state for next iteration
            prev_m1_state = m1_state
            prev_m2_state = m2_state

            # ========== OEE CALCULATION (Phase 6) ==========

            # --- Station 1 (M1) OEE ---
            # Availability = (TotalTime - DownTime) / TotalTime
            if m1_total_time > 0:
                m1_availability = max(0.0, min(1.0, (m1_total_time - m1_down_time) / m1_total_time))
            else:
                m1_availability = 0.0

            # Performance = ActualOutput / TheoreticalOutput
            # AvailableTime = time when not starved (material was available)
            m1_available_time = m1_processing_time + m1_blocked_time + m1_idle_time
            if m1_available_time > 0 and m1_nominal_cycle_time > 0:
                m1_theoretical_output = m1_available_time / m1_nominal_cycle_time
                m1_performance = max(0.0, min(1.0, m1_partcount / m1_theoretical_output))
            else:
                m1_theoretical_output = 0.0
                m1_performance = 0.0

            # Quality = GoodParts / TotalParts (Phase 6: assume 100%)
            m1_good_parts = m1_partcount
            m1_defective_parts = 0
            if m1_partcount > 0:
                m1_quality = 1.0  # Phase 8 will track defects
            else:
                m1_quality = 0.0  # No parts produced yet

            # OEE = Availability × Performance × Quality
            m1_oee = m1_availability * m1_performance * m1_quality

            # --- Station 2 (M2) OEE ---
            # (Same pattern, but M2 has no health degradation so down_time always 0)
            if m2_total_time > 0:
                m2_availability = max(0.0, min(1.0, (m2_total_time - m2_down_time) / m2_total_time))
            else:
                m2_availability = 0.0

            m2_available_time = m2_processing_time + m2_blocked_time + m2_idle_time
            if m2_available_time > 0 and m2_nominal_cycle_time > 0:
                m2_theoretical_output = m2_available_time / m2_nominal_cycle_time
                m2_performance = max(0.0, min(1.0, m2_partcount / m2_theoretical_output))
            else:
                m2_theoretical_output = 0.0
                m2_performance = 0.0

            m2_good_parts = m2_partcount
            m2_defective_parts = 0
            if m2_partcount > 0:
                m2_quality = 1.0
            else:
                m2_quality = 0.0

            m2_oee = m2_availability * m2_performance * m2_quality

            # --- Line-Level OEE (Bottleneck-based) ---
            line_availability = min(m1_availability, m2_availability)  # Weakest link
            line_performance = min(m1_performance, m2_performance)     # Weakest link
            line_quality = min(m1_quality, m2_quality)                # Worst quality
            line_oee = line_availability * line_performance * line_quality

            # --- Write KPIs back to OPC UA ---
            vars_["simtime"].set_value(current_sim_time)
            vars_["throughput"].set_value(current_throughput)
            vars_["total_wip"].set_value(total_wip)

            # Line-Level OEE
            vars_["line_availability"].set_value(line_availability)
            vars_["line_performance"].set_value(line_performance)
            vars_["line_quality"].set_value(line_quality)
            vars_["line_oee"].set_value(line_oee)

            vars_["m1_partcount"].set_value(m1_partcount)
            vars_["m1_state"].set_value(m1_state)
            vars_["m1_utilisation"].set_value(m1_utilisation)
            vars_["m1_health"].set_value(m1_health_state)
            vars_["m1_health_pct"].set_value(m1_health_percent)
            vars_["m1_blocked_time"].set_value(m1_blocked_time)
            vars_["m1_starved_time"].set_value(m1_starved_time)
            vars_["m1_down_time"].set_value(m1_down_time)
            vars_["m1_processing_time"].set_value(m1_processing_time)
            vars_["m1_idle_time"].set_value(m1_idle_time)

            # Station 1 OEE
            vars_["m1_availability"].set_value(m1_availability)
            vars_["m1_performance"].set_value(m1_performance)
            vars_["m1_quality"].set_value(m1_quality)
            vars_["m1_oee"].set_value(m1_oee)
            vars_["m1_good_parts"].set_value(m1_good_parts)
            vars_["m1_defective_parts"].set_value(m1_defective_parts)
            vars_["m1_theoretical"].set_value(m1_theoretical_output)

            vars_["b1_level"].set_value(b1_level)
            vars_["b1_capacity"].set_value(b1_capacity)

            vars_["m2_partcount"].set_value(m2_partcount)
            vars_["m2_state"].set_value(m2_state)
            vars_["m2_utilisation"].set_value(m2_utilisation)
            vars_["m2_blocked_time"].set_value(m2_blocked_time)
            vars_["m2_starved_time"].set_value(m2_starved_time)
            vars_["m2_down_time"].set_value(m2_down_time)
            vars_["m2_processing_time"].set_value(m2_processing_time)
            vars_["m2_idle_time"].set_value(m2_idle_time)

            # Station 2 OEE
            vars_["m2_availability"].set_value(m2_availability)
            vars_["m2_performance"].set_value(m2_performance)
            vars_["m2_quality"].set_value(m2_quality)
            vars_["m2_oee"].set_value(m2_oee)
            vars_["m2_good_parts"].set_value(m2_good_parts)
            vars_["m2_defective_parts"].set_value(m2_defective_parts)
            vars_["m2_theoretical"].set_value(m2_theoretical_output)

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