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


def calculate_oee(
    partcount: int,
    metrics: dict,
    cycle_time: float,
    good_parts: int = None,
    defective_parts: int = None
) -> dict:
    """
    Calculate OEE metrics (Availability, Performance, Quality, OEE).

    Args:
        partcount: Total parts produced by this machine
        metrics: Dictionary with time counters
        cycle_time: Nominal cycle time
        good_parts: Parts without defects (Phase 8 - optional)
        defective_parts: Parts with defects (Phase 8 - optional)

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

    # Quality = GoodParts / TotalParts (Phase 8: real tracking)
    if good_parts is None:
        # Fallback to Phase 7 behavior (backward compatibility)
        good_parts = partcount
        defective_parts = 0
        quality = 1.0 if partcount > 0 else 0.0
    else:
        # Phase 8: Use actual defect data
        if partcount > 0:
            quality = max(0.0, min(1.0, good_parts / partcount))
        else:
            quality = 0.0

    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": availability * performance * quality,
        "good_parts": good_parts,
        "defective_parts": defective_parts,
        "theoretical_output": theoretical_output,
    }


def calculate_defects(
    prev_partcount: int,
    current_partcount: int,
    base_defect_rate: float,
    health_state: int = 0,
    health_multiplier: float = 3.0,
    enable_health_correlation: bool = False
) -> int:
    """
    Calculate number of defective parts produced in this time step.

    Uses probabilistic defect generation with optional health correlation.

    Args:
        prev_partcount: Parts produced up to previous time step
        current_partcount: Parts produced up to current time step
        base_defect_rate: Baseline defect rate (0.0-1.0)
        health_state: 0=healthy, 1=failed (only used if enable_health_correlation=True)
        health_multiplier: Scales defect rate when machine degrades (default 3.0)
        enable_health_correlation: Link defect rate to machine health

    Returns:
        int: Number of defective parts produced in this time step
    """
    import random

    # How many new parts were produced?
    new_parts = current_partcount - prev_partcount
    if new_parts <= 0:
        return 0

    # Calculate effective defect rate
    if enable_health_correlation:
        effective_rate = base_defect_rate * (1 + health_multiplier * health_state)
    else:
        effective_rate = base_defect_rate

    # Clamp to valid range
    effective_rate = max(0.0, min(1.0, effective_rate))

    # Probabilistic defect generation (per-part Bernoulli trial)
    defects = 0
    for _ in range(new_parts):
        if random.random() < effective_rate:
            defects += 1

    return defects


def mark_part_defective(part, machine_name: str, defect_type: str = "quality"):
    """
    Mark a part as defective with traceability information (Phase 8b).

    Args:
        part: Simantha Part object
        machine_name: Name of machine that produced the defect
        defect_type: Type of defect (default: "quality")
    """
    part.is_defective = True
    part.failed_at_machine = machine_name
    part.defect_type = defect_type


def analyze_part_quality(sink) -> dict:
    """
    Analyze quality of individual parts in sink (Phase 8b).

    Args:
        sink: Simantha Sink object with collect_parts=True

    Returns:
        dict: Quality analysis metrics
    """
    if not hasattr(sink, 'contents') or len(sink.contents) == 0:
        return {
            "total_parts": 0,
            "good_parts": 0,
            "defective_parts": 0,
            "first_pass_yield": 0.0,
            "defect_by_machine": {}
        }

    total_parts = len(sink.contents)
    defective_parts = []
    defect_by_machine = {}

    for part in sink.contents:
        if hasattr(part, 'is_defective') and part.is_defective:
            defective_parts.append(part)

            # Track which machine produced the defect
            if hasattr(part, 'failed_at_machine'):
                machine = part.failed_at_machine
                defect_by_machine[machine] = defect_by_machine.get(machine, 0) + 1

    good_parts = total_parts - len(defective_parts)
    first_pass_yield = good_parts / total_parts if total_parts > 0 else 0.0

    return {
        "total_parts": total_parts,
        "good_parts": good_parts,
        "defective_parts": len(defective_parts),
        "first_pass_yield": first_pass_yield,
        "defect_by_machine": defect_by_machine
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
        cycle_time = int(machine_cfg.get("cycle_time", 1))  # Convert to int for Simantha
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
    import random

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Simantha OPC UA Server")
    parser.add_argument("--scenario", default="balanced_line",
                       help="Scenario name from line_models.yaml (default: balanced_line)")
    parser.add_argument("--seed", type=int, default=None,
                       help="Random seed for reproducible defect generation (Phase 8)")
    args = parser.parse_args()

    # Set random seed if provided (Phase 8)
    if args.seed is not None:
        random.seed(args.seed)
        print(f"Using random seed: {args.seed}")

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

        # Phase 8: Quality parameters
        base_defect_rate = machine_cfg.get("defect_rate", 0.0)
        health_multiplier = machine_cfg.get("health_multiplier", 3.0)

        machine_metrics[machine_name] = {
            "partcount": 0,
            "blocked_time": 0.0,
            "starved_time": 0.0,
            "down_time": 0.0,
            "processing_time": 0.0,
            "idle_time": 0.0,
            "prev_state": "IDLE",
            "cycle_time": cycle_time,

            # Phase 8: Quality tracking
            "good_parts": 0,
            "defective_parts": 0,
            "base_defect_rate": base_defect_rate,
            "health_multiplier": health_multiplier,
        }

    server.start()
    print(f"OPC UA server started at opc.tcp://localhost:4840/simantha/")
    print(f"Scenario: {args.scenario} ({len(machines)} machines, {len(buffers)} buffers)")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            # Read controls from OPC UA
            pause_line = bool(opcua_vars["system"]["pause_line"].get_value())
            interarrival = float(opcua_vars["system"]["interarrival_time"].get_value())

            # Push interarrival time into Simantha source
            source.interarrival_time = interarrival

            # Step simulation
            if not pause_line:
                sim_time += sim_step
                system.simulate(simulation_time=sim_time)

            # Monotonic part counter
            current_sink_level = sink.level
            if current_sink_level > prev_sink_level:
                delta_parts = current_sink_level - prev_sink_level
                total_parts_produced += delta_parts
                prev_sink_level = current_sink_level
            elif current_sink_level < prev_sink_level:
                prev_sink_level = current_sink_level

            # Total WIP (sum of all buffer levels)
            total_wip = sum(buffer.level for buffer in buffers.values())

            # Maintenance status
            if maintainer is not None:
                try:
                    # Check if maintainer is currently repairing
                    maint_active = len(maintainer.in_progress) > 0
                    # Queue length (machines waiting for maintenance)
                    maint_queue_length = len(maintainer.queue)
                    # Total repairs completed (rough estimate from maintainer stats)
                    total_repairs = maintainer.total_throughput if hasattr(maintainer, 'total_throughput') else 0
                except AttributeError:
                    # Fallback if Simantha Maintainer API differs
                    maint_active = False
                    maint_queue_length = 0
                    total_repairs = 0
            else:
                maint_active = False
                maint_queue_length = 0
                total_repairs = 0

            # Update machine states and metrics (LOOP instead of m1/m2 specific)
            for machine_name, machine_obj in machines.items():
                metrics = machine_metrics[machine_name]

                # Store previous partcount for defect calculation (Phase 8)
                prev_partcount = metrics["partcount"]

                # Accumulate time based on previous state
                if not pause_line:
                    accumulate_time(metrics, metrics["prev_state"], sim_step)

                # Detect current state
                machine_cfg = next(m for m in config["machines"] if m["name"] == machine_name)
                enable_health = machine_cfg.get("enable_degradation", False)
                health_state = machine_obj.health if enable_health else 0

                # Check if this machine is being repaired
                machine_maint_active = False
                if maintainer:
                    try:
                        machine_maint_active = machine_obj in maintainer.in_progress
                    except AttributeError:
                        machine_maint_active = False

                current_state = detect_machine_state(machine_obj, pause_line, health_state, machine_maint_active)

                # Update state
                metrics["prev_state"] = current_state

                # Part count (all machines in series produce same total)
                metrics["partcount"] = total_parts_produced

                # Phase 8: Calculate defects produced this step
                new_defects = calculate_defects(
                    prev_partcount=prev_partcount,
                    current_partcount=metrics["partcount"],
                    base_defect_rate=metrics["base_defect_rate"],
                    health_state=health_state,
                    health_multiplier=metrics["health_multiplier"],
                    enable_health_correlation=enable_health
                )
                metrics["defective_parts"] += new_defects
                metrics["good_parts"] = metrics["partcount"] - metrics["defective_parts"]

                # Phase 8b: Mark individual parts as defective
                if new_defects > 0 and hasattr(sink, 'contents') and len(sink.contents) > 0:
                    # Mark the most recently produced parts as defective
                    # We mark approximately the last new_defects parts
                    for i in range(1, min(new_defects + 1, len(sink.contents) + 1)):
                        part = sink.contents[-i]
                        if not hasattr(part, 'is_defective') or not part.is_defective:
                            mark_part_defective(part, machine_name, defect_type="quality")

                # Calculate OEE (Phase 8: pass quality data)
                oee_result = calculate_oee(
                    metrics["partcount"],
                    metrics,
                    metrics["cycle_time"],
                    good_parts=metrics["good_parts"],
                    defective_parts=metrics["defective_parts"]
                )

                # Calculate utilization
                total_time = sum([metrics[k] for k in ["processing_time", "blocked_time",
                                                        "starved_time", "down_time", "idle_time"]])
                utilisation = metrics["processing_time"] / total_time if total_time > 0 else 0.0

                # Write to OPC UA
                machine_vars = opcua_vars["machines"][machine_name]
                machine_vars["state"].set_value(current_state)
                machine_vars["partcount"].set_value(metrics["partcount"])
                machine_vars["utilisation"].set_value(utilisation)
                machine_vars["blocked_time"].set_value(metrics["blocked_time"])
                machine_vars["starved_time"].set_value(metrics["starved_time"])
                machine_vars["down_time"].set_value(metrics["down_time"])
                machine_vars["processing_time"].set_value(metrics["processing_time"])
                machine_vars["idle_time"].set_value(metrics["idle_time"])

                # Health (if enabled)
                if "health" in machine_vars:
                    health_pct = 100.0 * (1 - health_state)
                    machine_vars["health"].set_value(health_state)
                    machine_vars["health_pct"].set_value(health_pct)

                # OEE
                machine_vars["availability"].set_value(oee_result["availability"])
                machine_vars["performance"].set_value(oee_result["performance"])
                machine_vars["quality"].set_value(oee_result["quality"])
                machine_vars["oee"].set_value(oee_result["oee"])
                machine_vars["good_parts"].set_value(oee_result["good_parts"])
                machine_vars["defective_parts"].set_value(oee_result["defective_parts"])
                machine_vars["theoretical"].set_value(oee_result["theoretical_output"])

            # Update buffer levels
            for buffer_name, buffer_obj in buffers.items():
                buffer_vars = opcua_vars["buffers"][buffer_name]
                buffer_vars["level"].set_value(buffer_obj.level)

            # Line-level OEE (bottleneck logic - minimum of all stations)
            all_oee_results = [calculate_oee(machine_metrics[m]["partcount"],
                                             machine_metrics[m],
                                             machine_metrics[m]["cycle_time"])
                              for m in machines.keys()]

            line_availability = min(result["availability"] for result in all_oee_results) if all_oee_results else 0.0
            line_performance = min(result["performance"] for result in all_oee_results) if all_oee_results else 0.0
            line_quality = min(result["quality"] for result in all_oee_results) if all_oee_results else 0.0
            line_oee = line_availability * line_performance * line_quality

            # Write system and line-level KPIs to OPC UA
            opcua_vars["system"]["simtime"].set_value(sim_time)
            opcua_vars["system"]["throughput"].set_value(total_parts_produced)
            opcua_vars["line_kpis"]["total_wip"].set_value(total_wip)
            opcua_vars["line_kpis"]["line_availability"].set_value(line_availability)
            opcua_vars["line_kpis"]["line_performance"].set_value(line_performance)
            opcua_vars["line_kpis"]["line_quality"].set_value(line_quality)
            opcua_vars["line_kpis"]["line_oee"].set_value(line_oee)

            # Write maintenance status
            opcua_vars["maintenance"]["active"].set_value(maint_active)
            opcua_vars["maintenance"]["queue"].set_value(maint_queue_length)
            opcua_vars["maintenance"]["total_repairs"].set_value(total_repairs)

            time.sleep(real_step)

    except KeyboardInterrupt:
        print("\n\nSimulation stopped by user")

        # Phase 8b: Print part quality analysis
        quality_analysis = analyze_part_quality(sink)
        print(f"\n=== Part Quality Analysis ===")
        print(f"Total Parts: {quality_analysis['total_parts']}")
        print(f"Good Parts: {quality_analysis['good_parts']}")
        print(f"Defective Parts: {quality_analysis['defective_parts']}")
        print(f"First Pass Yield: {quality_analysis['first_pass_yield']:.2%}")

        if quality_analysis['defect_by_machine']:
            print(f"\nDefects by Machine:")
            for machine, count in quality_analysis['defect_by_machine'].items():
                print(f"  {machine}: {count} defects")
        else:
            print(f"\nNo defects detected (all parts passed quality checks)")

        print("\nStopping server...")
    finally:
        server.stop()
        print("Server stopped.")


if __name__ == "__main__":
    main()
