import time

from opcua import Server
from simantha import Source, Machine, Buffer, Sink, System, Maintainer
from config_loader import load_line_config


# Machine health degradation matrix (2-state: healthy → failed)
# State 0: healthy, State 1: failed (absorbing until maintenance)
DEGRADATION_MATRIX = [
    [0.99, 0.01],  # from healthy: 99% stay healthy, 1% degrade per step
    [0.0, 1.0],    # from failed: stay failed until maintainer repairs
]


# ========== HELPER FUNCTIONS (Phase 7) ==========

def create_station_node(parent_node, opcua_idx: int, station_name: str, enable_health: bool = False):
    """
    Create OPC UA variables for a single station.

    Args:
        parent_node: Parent OPC UA node
        opcua_idx: OPC UA namespace index
        station_name: Station node name (e.g., "Station1", "Station2")
        enable_health: Whether to create health variables

    Returns:
        dict: Dictionary of variable objects
    """
    station_node = parent_node.add_object(opcua_idx, station_name)

    vars_dict = {}
    vars_dict["state"] = station_node.add_variable(opcua_idx, "State", "IDLE")
    vars_dict["partcount"] = station_node.add_variable(opcua_idx, "PartCount", 0)
    vars_dict["utilisation"] = station_node.add_variable(opcua_idx, "Utilisation", 0.0)

    # Time tracking (5 variables)
    vars_dict["blocked_time"] = station_node.add_variable(opcua_idx, "BlockedTime", 0.0)
    vars_dict["starved_time"] = station_node.add_variable(opcua_idx, "StarvedTime", 0.0)
    vars_dict["down_time"] = station_node.add_variable(opcua_idx, "DownTime", 0.0)
    vars_dict["processing_time"] = station_node.add_variable(opcua_idx, "ProcessingTime", 0.0)
    vars_dict["idle_time"] = station_node.add_variable(opcua_idx, "IdleTime", 0.0)

    # Health (optional - only for machines with degradation)
    if enable_health:
        vars_dict["health"] = station_node.add_variable(opcua_idx, "HealthState", 0)
        vars_dict["health_pct"] = station_node.add_variable(opcua_idx, "HealthPercent", 100.0)

    # OEE sub-node (7 variables)
    oee_node = station_node.add_object(opcua_idx, "OEE")
    vars_dict["availability"] = oee_node.add_variable(opcua_idx, "Availability", 0.0)
    vars_dict["performance"] = oee_node.add_variable(opcua_idx, "Performance", 0.0)
    vars_dict["quality"] = oee_node.add_variable(opcua_idx, "Quality", 1.0)
    vars_dict["oee"] = oee_node.add_variable(opcua_idx, "OEE", 0.0)
    vars_dict["good_parts"] = oee_node.add_variable(opcua_idx, "GoodPartCount", 0)
    vars_dict["defective_parts"] = oee_node.add_variable(opcua_idx, "DefectivePartCount", 0)
    vars_dict["theoretical"] = oee_node.add_variable(opcua_idx, "TheoreticalOutput", 0.0)

    return vars_dict


def create_buffer_node(parent_node, opcua_idx: int, buffer_name: str, capacity: int):
    """
    Create OPC UA variables for a single buffer.

    Args:
        parent_node: Parent OPC UA node
        opcua_idx: OPC UA namespace index
        buffer_name: Buffer node name (e.g., "Buffer1", "Buffer2")
        capacity: Buffer capacity

    Returns:
        dict: Dictionary of variable objects
    """
    buffer_node = parent_node.add_object(opcua_idx, buffer_name)

    vars_dict = {}
    vars_dict["level"] = buffer_node.add_variable(opcua_idx, "CurrentLevel", 0)
    vars_dict["capacity"] = buffer_node.add_variable(opcua_idx, "Capacity", capacity)

    return vars_dict


def detect_machine_state(machine, pause_line: bool, health_state: int = 0, maint_active: bool = False) -> str:
    """
    Determine machine state based on Simantha flags and health.

    Args:
        machine: Simantha Machine object
        pause_line: Global pause flag
        health_state: 0=healthy, 1=failed
        maint_active: True if maintainer is currently repairing this machine

    Returns:
        State string: IDLE, PROCESSING, BLOCKED, STARVED, PAUSED, FAILED, UNDER_REPAIR
    """
    if pause_line:
        return "PAUSED"

    if health_state == 1:
        return "UNDER_REPAIR" if maint_active else "FAILED"

    if machine.blocked:
        return "BLOCKED"
    elif machine.starved:
        return "STARVED"
    elif machine.has_part:
        return "PROCESSING"
    else:
        return "IDLE"


def accumulate_time(metrics: dict, current_state: str, sim_step: float) -> None:
    """
    Update time accumulators based on current state (modifies metrics in-place).

    Args:
        metrics: Dictionary with time counters
        current_state: Current machine state
        sim_step: Time delta to add
    """
    state_map = {
        "BLOCKED": "blocked_time",
        "STARVED": "starved_time",
        "FAILED": "down_time",
        "UNDER_REPAIR": "down_time",
        "PROCESSING": "processing_time",
        "IDLE": "idle_time",
    }

    time_key = state_map.get(current_state)
    if time_key:
        metrics[time_key] += sim_step


def calculate_oee(partcount: int, metrics: dict, cycle_time: float) -> dict:
    """
    Calculate OEE metrics (Availability, Performance, Quality, OEE).

    Args:
        partcount: Total parts produced by this machine
        metrics: Dictionary with time counters
        cycle_time: Nominal cycle time

    Returns:
        dict: OEE metrics (availability, performance, quality, oee, good_parts, defective_parts, theoretical_output)
    """
    total_time = (
        metrics["processing_time"] + metrics["blocked_time"] +
        metrics["starved_time"] + metrics["down_time"] + metrics["idle_time"]
    )

    # Availability = (TotalTime - DownTime) / TotalTime
    if total_time > 0:
        availability = max(0.0, min(1.0, (total_time - metrics["down_time"]) / total_time))
    else:
        availability = 0.0

    # Performance = ActualOutput / TheoreticalOutput
    available_time = metrics["processing_time"] + metrics["blocked_time"] + metrics["idle_time"]
    if available_time > 0 and cycle_time > 0:
        theoretical_output = available_time / cycle_time
        performance = max(0.0, min(1.0, partcount / theoretical_output))
    else:
        theoretical_output = 0.0
        performance = 0.0

    # Quality = GoodParts / TotalParts (Phase 7: assume 100%)
    quality = 1.0 if partcount > 0 else 0.0

    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": availability * performance * quality,
        "good_parts": partcount,
        "defective_parts": 0,
        "theoretical_output": theoretical_output,
    }


# ========== SYSTEM BUILDING ==========

def build_simantha_system(config: dict):
    """
    Build Simantha system from configuration.

    Args:
        config: Dict with keys 'machines', 'buffers', 'maintainer'
                Example:
                {
                    "machines": [
                        {"name": "M1", "cycle_time": 1.0, "enable_degradation": true, ...},
                        {"name": "M2", "cycle_time": 1.0, "enable_degradation": false},
                        ...
                    ],
                    "buffers": [
                        {"name": "B1", "capacity": 10, "upstream": "M1", "downstream": "M2"},
                        ...
                    ],
                    "maintainer": {"enabled": true, "capacity": 1}
                }

    Returns:
        tuple: (system, source, sink, machines_dict, buffers_dict, maintainer)
               machines_dict: {"M1": machine_obj, "M2": machine_obj, ...}
               buffers_dict: {"B1": buffer_obj, "B2": buffer_obj, ...}
    """
    source = Source()
    sink = Sink(collect_parts=True)

    # Create machines from config
    machines = {}
    for machine_cfg in config["machines"]:
        name = machine_cfg["name"]
        cycle_time = machine_cfg.get("cycle_time", 1.0)
        enable_degradation = machine_cfg.get("enable_degradation", False)

        if enable_degradation:
            degradation_matrix = machine_cfg.get("degradation_matrix", DEGRADATION_MATRIX)
            cbm_threshold = machine_cfg.get("cbm_threshold", 1)
            machines[name] = Machine(
                name=name,
                cycle_time=cycle_time,
                degradation_matrix=degradation_matrix,
                cbm_threshold=cbm_threshold
            )
        else:
            machines[name] = Machine(name=name, cycle_time=cycle_time)

    # Create buffers from config
    buffers = {}
    for buffer_cfg in config["buffers"]:
        name = buffer_cfg["name"]
        capacity = buffer_cfg.get("capacity", 10)
        buffers[name] = Buffer(name=name, capacity=capacity)

    # Create maintainer if enabled
    maintainer_cfg = config.get("maintainer", {"enabled": False})
    if maintainer_cfg.get("enabled", False):
        maintainer = Maintainer(capacity=maintainer_cfg.get("capacity", 1))
    else:
        maintainer = None

    # Define routing (serial topology: Source → M1 → B1 → M2 → B2 → M3 → Sink)
    machine_list = list(machines.values())
    buffer_list = list(buffers.values())

    source.define_routing(downstream=[machine_list[0]])

    for i, machine in enumerate(machine_list):
        if i == 0:
            # First machine: Source → M1 → B1
            machine.define_routing(upstream=[source], downstream=[buffer_list[0]])
        elif i == len(machine_list) - 1:
            # Last machine: BN → MN → Sink
            machine.define_routing(upstream=[buffer_list[i-1]], downstream=[sink])
        else:
            # Middle machines: Bi → Mi → Bi+1
            machine.define_routing(upstream=[buffer_list[i-1]], downstream=[buffer_list[i]])

    for i, buffer in enumerate(buffer_list):
        buffer.define_routing(upstream=[machine_list[i]], downstream=[machine_list[i+1]])

    sink.define_routing(upstream=[machine_list[-1]])

    # Create System
    all_objects = [source] + machine_list + buffer_list + [sink]
    if maintainer is not None:
        system = System(objects=all_objects, maintainer=maintainer)
    else:
        system = System(objects=all_objects)

    return system, source, sink, machines, buffers, maintainer


def build_opcua_server(config: dict):
    """
    Build OPC UA server with dynamic node creation from config.

    Args:
        config: Dict with keys 'machines', 'buffers', 'maintainer'

    Returns:
        tuple: (server, opcua_vars, idx)
               opcua_vars is a structured dict:
               {
                   "system": {simtime, throughput, pause_line, interarrival_time},
                   "line_kpis": {total_wip, line_availability, ...},
                   "machines": {"M1": {...}, "M2": {...}, ...},
                   "buffers": {"B1": {...}, "B2": {...}, ...},
                   "maintenance": {active, queue, total_repairs}
               }
    """
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

    # Dynamic station creation (Phase 7)
    machines_vars = {}
    for i, machine_cfg in enumerate(config["machines"], start=1):
        machine_name = machine_cfg["name"]
        station_name = f"Station{i}"  # "Station1", "Station2", "Station3", ...
        enable_health = machine_cfg.get("enable_degradation", False)

        station_vars = create_station_node(line1, idx, station_name, enable_health)
        machines_vars[machine_name] = station_vars

    # Dynamic buffer creation (Phase 7)
    buffers_vars = {}
    for i, buffer_cfg in enumerate(config["buffers"], start=1):
        buffer_name = buffer_cfg["name"]
        buffer_node_name = f"Buffer{i}"  # "Buffer1", "Buffer2", "Buffer3", ...
        capacity = buffer_cfg.get("capacity", 10)

        buffer_vars = create_buffer_node(line1, idx, buffer_node_name, capacity)
        buffers_vars[buffer_name] = buffer_vars

    # Maintenance (unchanged)
    maintenance_node = line1.add_object(idx, "Maintenance")
    var_maint_active = maintenance_node.add_variable(idx, "MaintenanceActive", False)
    var_maint_queue = maintenance_node.add_variable(idx, "QueueLength", 0)
    var_total_repairs = maintenance_node.add_variable(idx, "TotalRepairs", 0)

    # Writable controls
    writable_vars = [var_pause_line, var_interarrival]
    for v in writable_vars:
        v.set_writable()

    # Return structured dictionary
    opcua_vars = {
        "system": {
            "simtime": var_simtime,
            "throughput": var_throughput,
            "pause_line": var_pause_line,
            "interarrival_time": var_interarrival,
        },
        "line_kpis": {
            "total_wip": var_total_wip,
            "line_availability": var_line_availability,
            "line_performance": var_line_performance,
            "line_quality": var_line_quality,
            "line_oee": var_line_oee,
        },
        "machines": machines_vars,  # {"M1": {...}, "M2": {...}, "M3": {...}}
        "buffers": buffers_vars,    # {"B1": {...}, "B2": {...}}
        "maintenance": {
            "active": var_maint_active,
            "queue": var_maint_queue,
            "total_repairs": var_total_repairs,
        }
    }

    return server, opcua_vars, idx


def main():
    import argparse

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Simantha OPC UA Server")
    parser.add_argument("--scenario", default="balanced_line",
                       help="Scenario name from line_models.yaml (default: balanced_line)")
    args = parser.parse_args()

    # Load configuration
    config = load_line_config(args.scenario)
    print(f"Loading scenario: {args.scenario}")

    # Build Simantha system from config
    system, source, sink, machines, buffers, maintainer = build_simantha_system(config)

    # Build OPC UA server from config
    server, opcua_vars, idx = build_opcua_server(config)

    sim_time = 0.0
    sim_step = 1.0
    real_step = 1.0

    # Manual part counter (monotonic, never decreases)
    prev_sink_level = 0
    total_parts_produced = 0

    # Initialize per-machine metrics dictionaries
    machine_metrics = {}
    for machine_name in machines.keys():
        # Find corresponding config to get cycle_time
        machine_cfg = next(m for m in config["machines"] if m["name"] == machine_name)
        cycle_time = machine_cfg.get("cycle_time", 1.0)

        machine_metrics[machine_name] = {
            "partcount": 0,
            "blocked_time": 0.0,
            "starved_time": 0.0,
            "down_time": 0.0,
            "processing_time": 0.0,
            "idle_time": 0.0,
            "prev_state": "IDLE",
            "cycle_time": cycle_time,
        }

    server.start()
    print(f"OPC UA server started at opc.tcp://localhost:4840/simantha/")
    print(f"Scenario: {args.scenario} ({len(machines)} machines, {len(buffers)} buffers)")
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