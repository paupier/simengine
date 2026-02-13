import time

from opcua import Server
from simantha import Source, Machine, Buffer, Sink, System, Maintainer
from config_loader import load_line_config
from advanced_machine import AdvancedMachine
from failure_modes import FailureMode
from spc_analytics import ProcessMonitor, SPCConfiguration
from shift_manager import create_shift_manager_from_config
from event_historian import create_historian_from_config, collect_step_events, collect_production_summary
from neo4j_historian import create_neo4j_historian_from_config
from quality_machine import QualityAwareMachine, QualityAdvancedMachine, QualityRoutingMixin


# Machine health degradation matrix (2-state: healthy → failed)
# State 0: healthy, State 1: failed (absorbing until maintenance)
DEGRADATION_MATRIX = [
    [0.99, 0.01],  # from healthy: 99% stay healthy, 1% degrade per step
    [0.0, 1.0],    # from failed: stay failed until maintainer repairs
]


# ========== HELPER FUNCTIONS (Phase 7) ==========

def create_station_node(parent_node, opcua_idx: int, station_name: str, enable_health: bool = False,
                        enable_failure_modes: bool = False, failure_mode_names: list = None,
                        enable_spc: bool = False, enable_quality_routing: bool = False):
    """
    Create OPC UA variables for a single station.

    Args:
        parent_node: Parent OPC UA node
        opcua_idx: OPC UA namespace index
        station_name: Station node name (e.g., "Station1", "Station2")
        enable_health: Whether to create health variables
        enable_failure_modes: Whether to create FailureModes/MaintenanceStrategy subnodes (Phase 10)
        failure_mode_names: List of failure mode names (e.g., ["mechanical", "electrical"])
        enable_spc: Whether to create SPC (Statistical Process Control) subnode (Phase 11)

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

    # Alarms sub-node (Phase 9)
    alarm_vars = create_alarms_node(station_node, opcua_idx, alarm_type="station")
    vars_dict.update({f"alarm_{k}": v for k, v in alarm_vars.items()})

    # FailureModes sub-node (Phase 10)
    if enable_failure_modes and failure_mode_names:
        fm_node = station_node.add_object(opcua_idx, "FailureModes")
        vars_dict["fm_active"] = fm_node.add_variable(opcua_idx, "ActiveFailureMode", "none")

        # Create variables for each failure mode
        for fm_name in failure_mode_names:
            prefix = fm_name.capitalize()
            vars_dict[f"fm_{fm_name}_count"] = fm_node.add_variable(opcua_idx, f"{prefix}FailureCount", 0)
            vars_dict[f"fm_{fm_name}_downtime"] = fm_node.add_variable(opcua_idx, f"{prefix}TotalDowntime", 0.0)
            vars_dict[f"fm_{fm_name}_mtbf"] = fm_node.add_variable(opcua_idx, f"{prefix}MTBF", 0.0)
            vars_dict[f"fm_{fm_name}_mttr"] = fm_node.add_variable(opcua_idx, f"{prefix}MTTR", 0.0)

        # MaintenanceStrategy sub-node
        ms_node = station_node.add_object(opcua_idx, "MaintenanceStrategy")
        vars_dict["ms_type"] = ms_node.add_variable(opcua_idx, "StrategyType", "corrective")
        vars_dict["ms_next_pm"] = ms_node.add_variable(opcua_idx, "NextPMScheduled", -1.0)
        vars_dict["ms_pm_count"] = ms_node.add_variable(opcua_idx, "PMCount", 0)
        vars_dict["ms_cm_count"] = ms_node.add_variable(opcua_idx, "CMCount", 0)

    # SPC sub-node (Phase 11)
    if enable_spc:
        spc_vars = create_spc_node(station_node, opcua_idx)
        vars_dict.update({f"spc_{k}": v for k, v in spc_vars.items()})

    # QualityRouting sub-node (Phase 14)
    if enable_quality_routing:
        qr_node = station_node.add_object(opcua_idx, "QualityRouting")
        vars_dict["qr_scrap_count"] = qr_node.add_variable(opcua_idx, "ScrapCount", 0)
        vars_dict["qr_rework_count"] = qr_node.add_variable(opcua_idx, "ReworkCount", 0)
        vars_dict["qr_rework_success_count"] = qr_node.add_variable(opcua_idx, "ReworkSuccessCount", 0)
        vars_dict["qr_rework_success_rate"] = qr_node.add_variable(opcua_idx, "ReworkSuccessRate", 0.0)
        vars_dict["qr_good_count"] = qr_node.add_variable(opcua_idx, "GoodCount", 0)

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

    # Alarms sub-node (Phase 9)
    alarm_vars = create_alarms_node(buffer_node, opcua_idx, alarm_type="buffer")
    vars_dict.update({f"alarm_{k}": v for k, v in alarm_vars.items()})

    return vars_dict


def create_alarms_node(parent_node, opcua_idx: int, alarm_type: str = "station"):
    """
    Create Alarms sub-node for a station or buffer.

    Args:
        parent_node: Parent OPC UA node (station or buffer)
        opcua_idx: OPC UA namespace index
        alarm_type: "station" or "buffer"

    Returns:
        dict: Dictionary of alarm variable objects
    """
    from datetime import datetime

    alarms_node = parent_node.add_object(opcua_idx, "Alarms")

    vars_dict = {}
    vars_dict["alarm_count"] = alarms_node.add_variable(opcua_idx, "ActiveAlarmCount", 0)
    vars_dict["last_alarm_time"] = alarms_node.add_variable(opcua_idx, "LastAlarmTime", datetime.now())
    vars_dict["last_alarm_message"] = alarms_node.add_variable(opcua_idx, "LastAlarmMessage", "")
    vars_dict["last_alarm_severity"] = alarms_node.add_variable(opcua_idx, "LastAlarmSeverity", "")

    if alarm_type == "station":
        vars_dict["alarm_failure"] = alarms_node.add_variable(opcua_idx, "MachineFailureActive", False)
        vars_dict["alarm_maintenance"] = alarms_node.add_variable(opcua_idx, "MaintenanceActive", False)
        vars_dict["alarm_quality"] = alarms_node.add_variable(opcua_idx, "QualityAlertActive", False)
    elif alarm_type == "buffer":
        vars_dict["alarm_high"] = alarms_node.add_variable(opcua_idx, "HighLevelWarningActive", False)
        vars_dict["alarm_low"] = alarms_node.add_variable(opcua_idx, "LowLevelWarningActive", False)

    return vars_dict


def create_spc_node(parent_node, opcua_idx: int):
    """
    Create SPC (Statistical Process Control) sub-node for a station (Phase 11).

    Args:
        parent_node: Parent OPC UA node (station)
        opcua_idx: OPC UA namespace index

    Returns:
        dict: Dictionary of SPC variable objects
    """
    spc_node = parent_node.add_object(opcua_idx, "SPC")

    vars_dict = {}

    # X-bar Chart sub-node
    xbar_node = spc_node.add_object(opcua_idx, "XBarChart")
    vars_dict["xbar_current"] = xbar_node.add_variable(opcua_idx, "XBar", 0.0)
    vars_dict["xbar_ucl"] = xbar_node.add_variable(opcua_idx, "UCL", 0.0)
    vars_dict["xbar_cl"] = xbar_node.add_variable(opcua_idx, "CL", 0.0)
    vars_dict["xbar_lcl"] = xbar_node.add_variable(opcua_idx, "LCL", 0.0)

    # R Chart sub-node
    r_node = spc_node.add_object(opcua_idx, "RChart")
    vars_dict["r_current"] = r_node.add_variable(opcua_idx, "Range", 0.0)
    vars_dict["r_ucl"] = r_node.add_variable(opcua_idx, "UCL", 0.0)
    vars_dict["r_cl"] = r_node.add_variable(opcua_idx, "CL", 0.0)
    vars_dict["r_lcl"] = r_node.add_variable(opcua_idx, "LCL", 0.0)

    # Capability sub-node
    cap_node = spc_node.add_object(opcua_idx, "Capability")
    vars_dict["cp"] = cap_node.add_variable(opcua_idx, "Cp", 0.0)
    vars_dict["cpk"] = cap_node.add_variable(opcua_idx, "Cpk", 0.0)
    vars_dict["pp"] = cap_node.add_variable(opcua_idx, "Pp", 0.0)
    vars_dict["ppk"] = cap_node.add_variable(opcua_idx, "Ppk", 0.0)
    vars_dict["sigma_level"] = cap_node.add_variable(opcua_idx, "SigmaLevel", 0.0)

    # Status sub-node
    status_node = spc_node.add_object(opcua_idx, "Status")
    vars_dict["in_control"] = status_node.add_variable(opcua_idx, "InControl", True)
    vars_dict["violations"] = status_node.add_variable(opcua_idx, "Violations", "")
    vars_dict["total_samples"] = status_node.add_variable(opcua_idx, "TotalSamples", 0)
    vars_dict["num_subgroups"] = status_node.add_variable(opcua_idx, "NumSubgroups", 0)

    return vars_dict


def create_shift_node(parent_node, opcua_idx: int):
    """
    Create Shift tracking sub-node (Phase 12).

    Args:
        parent_node: Parent OPC UA node (usually Line1)
        opcua_idx: OPC UA namespace index

    Returns:
        dict: Dictionary of shift variable objects
    """
    shift_node = parent_node.add_object(opcua_idx, "Shift")

    vars_dict = {}

    # Current shift information
    vars_dict["shift_number"] = shift_node.add_variable(opcua_idx, "CurrentShiftNumber", 1)
    vars_dict["shift_name"] = shift_node.add_variable(opcua_idx, "CurrentShiftName", "")
    vars_dict["shift_start_time"] = shift_node.add_variable(opcua_idx, "ShiftStartTime", 0.0)
    vars_dict["shift_end_time"] = shift_node.add_variable(opcua_idx, "ShiftEndTime", 0.0)
    vars_dict["shift_duration"] = shift_node.add_variable(opcua_idx, "ShiftDuration", 0.0)
    vars_dict["shift_elapsed"] = shift_node.add_variable(opcua_idx, "ShiftElapsedTime", 0.0)
    vars_dict["shift_remaining"] = shift_node.add_variable(opcua_idx, "ShiftTimeRemaining", 0.0)

    # Current shift metrics (reset at shift end)
    current_node = shift_node.add_object(opcua_idx, "CurrentShift")
    vars_dict["current_parts"] = current_node.add_variable(opcua_idx, "PartsProduced", 0)
    vars_dict["current_good"] = current_node.add_variable(opcua_idx, "GoodParts", 0)
    vars_dict["current_defects"] = current_node.add_variable(opcua_idx, "DefectiveParts", 0)
    vars_dict["current_defect_rate"] = current_node.add_variable(opcua_idx, "DefectRate", 0.0)
    vars_dict["current_availability"] = current_node.add_variable(opcua_idx, "Availability", 0.0)
    vars_dict["current_performance"] = current_node.add_variable(opcua_idx, "Performance", 0.0)
    vars_dict["current_quality"] = current_node.add_variable(opcua_idx, "Quality", 1.0)
    vars_dict["current_oee"] = current_node.add_variable(opcua_idx, "OEE", 0.0)

    # Previous shift summary (for reporting)
    prev_node = shift_node.add_object(opcua_idx, "PreviousShift")
    vars_dict["prev_shift_number"] = prev_node.add_variable(opcua_idx, "ShiftNumber", 0)
    vars_dict["prev_shift_name"] = prev_node.add_variable(opcua_idx, "ShiftName", "")
    vars_dict["prev_parts"] = prev_node.add_variable(opcua_idx, "PartsProduced", 0)
    vars_dict["prev_good"] = prev_node.add_variable(opcua_idx, "GoodParts", 0)
    vars_dict["prev_defects"] = prev_node.add_variable(opcua_idx, "DefectiveParts", 0)
    vars_dict["prev_defect_rate"] = prev_node.add_variable(opcua_idx, "DefectRate", 0.0)
    vars_dict["prev_oee"] = prev_node.add_variable(opcua_idx, "OEE", 0.0)

    # Overall totals (never reset)
    totals_node = shift_node.add_object(opcua_idx, "Totals")
    vars_dict["total_parts"] = totals_node.add_variable(opcua_idx, "TotalPartsProduced", 0)
    vars_dict["total_good"] = totals_node.add_variable(opcua_idx, "TotalGoodParts", 0)
    vars_dict["total_defects"] = totals_node.add_variable(opcua_idx, "TotalDefectiveParts", 0)
    vars_dict["total_defect_rate"] = totals_node.add_variable(opcua_idx, "TotalDefectRate", 0.0)
    vars_dict["total_shifts"] = totals_node.add_variable(opcua_idx, "TotalShiftsCompleted", 0)

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


def detect_machine_alarms(machine_name: str, current_state: str, metrics: dict, health_state: int,
                          machine_maint_active: bool, new_defects: int, new_parts: int) -> list:
    """
    Detect machine alarm transitions (active/inactive).

    Args:
        machine_name: Name of the machine
        current_state: Current state string (IDLE, PROCESSING, etc.)
        metrics: machine_metrics dictionary for this machine
        health_state: Health degradation state (0=healthy, 1=failed)
        machine_maint_active: True if maintenance is active on this machine
        new_defects: Number of new defects produced this step
        new_parts: Number of new parts produced this step

    Returns:
        list: [(alarm_type, severity, message, is_active, var_key), ...]
    """
    alarms = []

    # 1. Machine Failure Alarm (CRITICAL)
    if current_state == "FAILED" and not metrics["alarm_machine_failed_active"]:
        alarms.append((
            "MachineFailure", "CRITICAL",
            f"{machine_name} has failed - health degraded to critical state",
            True, "alarm_failure"
        ))
        metrics["alarm_machine_failed_active"] = True
    elif current_state != "FAILED" and metrics["alarm_machine_failed_active"]:
        alarms.append((
            "MachineFailure", "INFO",
            f"{machine_name} recovered from failure",
            False, "alarm_failure"
        ))
        metrics["alarm_machine_failed_active"] = False

    # 2. Maintenance Event (INFO)
    if machine_maint_active and not metrics["alarm_maintenance_active"]:
        alarms.append((
            "MaintenanceStart", "INFO",
            f"Maintenance started on {machine_name}",
            True, "alarm_maintenance"
        ))
        metrics["alarm_maintenance_active"] = True
    elif not machine_maint_active and metrics["alarm_maintenance_active"]:
        alarms.append((
            "MaintenanceEnd", "INFO",
            f"Maintenance completed on {machine_name}",
            False, "alarm_maintenance"
        ))
        metrics["alarm_maintenance_active"] = False

    # 3. Quality Alert (MEDIUM) - defect rate > 5%
    if new_parts > 0:
        defect_rate = new_defects / new_parts
        QUALITY_THRESHOLD = 0.05  # 5%

        if defect_rate > QUALITY_THRESHOLD and not metrics["alarm_quality_alert_active"]:
            alarms.append((
                "QualityAlert", "MEDIUM",
                f"{machine_name} defect rate {defect_rate:.1%} exceeds threshold {QUALITY_THRESHOLD:.1%}",
                True, "alarm_quality"
            ))
            metrics["alarm_quality_alert_active"] = True
        elif defect_rate <= QUALITY_THRESHOLD and metrics["alarm_quality_alert_active"]:
            alarms.append((
                "QualityAlert", "INFO",
                f"{machine_name} defect rate {defect_rate:.1%} returned to normal",
                False, "alarm_quality"
            ))
            metrics["alarm_quality_alert_active"] = False

    return alarms


def detect_buffer_alarms(buffer_name: str, buffer_level: int, buffer_capacity: int,
                         alarm_state: dict) -> list:
    """
    Detect buffer alarm transitions (high/low level warnings).

    Args:
        buffer_name: Name of the buffer
        buffer_level: Current buffer level
        buffer_capacity: Maximum buffer capacity
        alarm_state: Dictionary to track alarm states (modified in-place)

    Returns:
        list: [(alarm_type, severity, message, is_active, var_key), ...]
    """
    alarms = []

    # High level warning (>= 90% capacity)
    if buffer_level >= 0.9 * buffer_capacity and not alarm_state.get("alarm_high_active", False):
        alarms.append((
            "BufferHigh", "LOW",
            f"{buffer_name} level {buffer_level}/{buffer_capacity} (>90% full)",
            True, "alarm_high"
        ))
        alarm_state["alarm_high_active"] = True
    elif buffer_level < 0.9 * buffer_capacity and alarm_state.get("alarm_high_active", False):
        alarms.append((
            "BufferHigh", "INFO",
            f"{buffer_name} level returned to normal",
            False, "alarm_high"
        ))
        alarm_state["alarm_high_active"] = False

    # Low level warning (<= 10% capacity, but not empty)
    if 0 < buffer_level <= 0.1 * buffer_capacity and not alarm_state.get("alarm_low_active", False):
        alarms.append((
            "BufferLow", "LOW",
            f"{buffer_name} level {buffer_level}/{buffer_capacity} (<10% full)",
            True, "alarm_low"
        ))
        alarm_state["alarm_low_active"] = True
    elif (buffer_level > 0.1 * buffer_capacity or buffer_level == 0) and alarm_state.get("alarm_low_active", False):
        alarms.append((
            "BufferLow", "INFO",
            f"{buffer_name} level returned to normal",
            False, "alarm_low"
        ))
        alarm_state["alarm_low_active"] = False

    return alarms


def update_alarm_variables(node_vars: dict, alarms: list):
    """
    Update OPC UA alarm variables based on detected alarms.

    Args:
        node_vars: Dictionary of OPC UA variable nodes (from opcua_vars)
        alarms: List of (alarm_type, severity, message, is_active, var_key) tuples
    """
    from datetime import datetime

    if not alarms:
        return

    # Update alarm count (count active alarms)
    if "alarm_alarm_count" in node_vars:
        current_count = node_vars["alarm_alarm_count"].get_value()
        # Adjust count based on activations/deactivations
        for alarm in alarms:
            if alarm[3]:  # Activated (alarm[3] is is_active)
                current_count += 1
            else:  # Deactivated
                current_count = max(0, current_count - 1)
        node_vars["alarm_alarm_count"].set_value(current_count)

    # Update latest alarm metadata (for most recent alarm)
    latest_alarm = alarms[-1]  # Most recent
    alarm_type, severity, message, is_active, var_key = latest_alarm

    if "alarm_last_alarm_time" in node_vars:
        node_vars["alarm_last_alarm_time"].set_value(datetime.now())
    if "alarm_last_alarm_message" in node_vars:
        node_vars["alarm_last_alarm_message"].set_value(message)
    if "alarm_last_alarm_severity" in node_vars:
        node_vars["alarm_last_alarm_severity"].set_value(severity)

    # Update individual alarm flags
    for alarm in alarms:
        alarm_type, severity, message, is_active, var_key = alarm
        full_key = f"alarm_{var_key}"
        if full_key in node_vars:
            node_vars[full_key].set_value(is_active)


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


# ========== MAIN LOOP STEP FUNCTIONS ==========


def read_opcua_controls(opcua_vars):
    """Read writable control values from OPC UA clients."""
    pause_line = bool(opcua_vars["system"]["pause_line"].get_value())
    interarrival = float(opcua_vars["system"]["interarrival_time"].get_value())
    return pause_line, interarrival


def update_part_counter(sink_level, prev_sink_level, total_parts_produced):
    """Track production monotonically (sink.level can decrease during maintenance).

    Returns:
        tuple: (delta_parts, total_parts_produced, prev_sink_level)
    """
    delta_parts = 0
    if sink_level > prev_sink_level:
        delta_parts = sink_level - prev_sink_level
        total_parts_produced += delta_parts
        prev_sink_level = sink_level
    elif sink_level < prev_sink_level:
        prev_sink_level = sink_level
    return delta_parts, total_parts_produced, prev_sink_level


def check_shift_rotation(shift_manager, sim_time, pause_line):
    """Check and perform shift rotation if needed. Returns whether shift rotated."""
    if shift_manager and not pause_line:
        shift_rotated = shift_manager.check_shift_rotation(sim_time)
        if shift_rotated:
            print(f"\n[SHIFT CHANGE] Shift {shift_manager.current_shift_number} started: "
                  f"{shift_manager.shift_definitions[shift_manager.current_shift_index].name}")
        return shift_rotated
    return False


def collect_system_metrics(buffers, maintainer):
    """Collect system-level metrics: WIP, maintenance status.

    Returns:
        tuple: (total_wip, maint_active, maint_queue_length, total_repairs)
    """
    total_wip = sum(buffer.level for buffer in buffers.values())

    if maintainer is not None:
        try:
            maint_active = len(maintainer.in_progress) > 0
            maint_queue_length = len(maintainer.queue)
            total_repairs = maintainer.total_throughput if hasattr(maintainer, 'total_throughput') else 0
        except AttributeError:
            maint_active = False
            maint_queue_length = 0
            total_repairs = 0
    else:
        maint_active = False
        maint_queue_length = 0
        total_repairs = 0

    return total_wip, maint_active, maint_queue_length, total_repairs


def process_machine_step(machine_name, machine_obj, metrics, config_machines,
                         total_parts_produced, pause_line, sim_step, maintainer,
                         shift_manager, spc_monitors, opcua_vars, sink):
    """Process one simulation step for a single machine.

    Updates metrics, detects state, calculates OEE, updates alarms, SPC,
    and writes all OPC UA variables for this machine.

    Returns:
        list or None: Alarms triggered this step (for historian), or None.
    """
    # Store previous partcount for defect calculation
    prev_partcount = metrics["partcount"]

    # Accumulate time based on previous state
    if not pause_line:
        accumulate_time(metrics, metrics["prev_state"], sim_step)

    # Detect current state
    machine_cfg = next(m for m in config_machines if m["name"] == machine_name)
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
    metrics["prev_state"] = current_state

    # Part count (all machines in series produce same total)
    metrics["partcount"] = total_parts_produced

    # Quality routing: defect tracking
    if isinstance(machine_obj, QualityRoutingMixin):
        metrics["defective_parts"] = machine_obj._scrap_count + machine_obj._defective_count
        metrics["good_parts"] = machine_obj._good_count
        metrics["partcount"] = metrics["good_parts"] + metrics["defective_parts"]
        new_defects = metrics["defective_parts"] - (prev_partcount - metrics.get("prev_good", 0))
        if new_defects < 0:
            new_defects = 0
    else:
        # Statistical defect calculation (non-routing machines)
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

        # Mark individual parts as defective
        if new_defects > 0 and hasattr(sink, 'contents') and len(sink.contents) > 0:
            for i in range(1, min(new_defects + 1, len(sink.contents) + 1)):
                part = sink.contents[-i]
                if not hasattr(part, 'is_defective') or not part.is_defective:
                    mark_part_defective(part, machine_name, defect_type="quality")

    # Shift metrics update
    if shift_manager and not pause_line:
        shift_manager.update_machine_time(machine_name, sim_step, current_state)
        if current_state == "FAILED" and metrics["prev_state"] != "FAILED":
            shift_manager.record_failure(machine_name)

    # Alarm detection
    new_parts = metrics["partcount"] - prev_partcount
    machine_alarms = detect_machine_alarms(
        machine_name=machine_name,
        current_state=current_state,
        metrics=metrics,
        health_state=health_state,
        machine_maint_active=machine_maint_active,
        new_defects=new_defects,
        new_parts=new_parts
    )

    machine_vars = opcua_vars["machines"][machine_name]
    if machine_alarms:
        update_alarm_variables(machine_vars, machine_alarms)

    # OEE calculation
    oee_result = calculate_oee(
        metrics["partcount"],
        metrics,
        metrics["cycle_time"],
        good_parts=metrics["good_parts"],
        defective_parts=metrics["defective_parts"]
    )

    # Utilization
    total_time = sum(
        metrics[k] for k in ["processing_time", "blocked_time",
                              "starved_time", "down_time", "idle_time"]
    )
    utilisation = metrics["processing_time"] / total_time if total_time > 0 else 0.0

    # Write all OPC UA variables for this machine
    write_machine_opcua_vars(machine_vars, machine_obj, current_state, metrics,
                             utilisation, oee_result, health_state,
                             spc_monitors.get(machine_name), new_parts)

    return machine_alarms


def write_machine_opcua_vars(machine_vars, machine_obj, current_state, metrics,
                             utilisation, oee_result, health_state,
                             spc_monitor, new_parts):
    """Write all OPC UA variables for a single machine."""
    # Core state variables
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

    # Failure mode statistics
    if isinstance(machine_obj, AdvancedMachine):
        active_mode = machine_obj.get_active_failure_mode()
        machine_vars["fm_active"].set_value(active_mode)

        fm_stats = machine_obj.get_failure_mode_stats()
        for fm_name, stats in fm_stats.items():
            machine_vars[f"fm_{fm_name}_count"].set_value(stats["failure_count"])
            machine_vars[f"fm_{fm_name}_downtime"].set_value(stats["total_downtime"])
            machine_vars[f"fm_{fm_name}_mtbf"].set_value(stats["mtbf"])
            machine_vars[f"fm_{fm_name}_mttr"].set_value(stats["mttr"])

        maint_stats = machine_obj.get_maintenance_stats()
        machine_vars["ms_type"].set_value(maint_stats["strategy_type"])
        machine_vars["ms_pm_count"].set_value(maint_stats["pm_count"])
        machine_vars["ms_cm_count"].set_value(maint_stats["cm_count"])
        machine_vars["ms_next_pm"].set_value(maint_stats["next_pm_time"])

    # SPC analytics
    if spc_monitor:
        if new_parts > 0:
            for _ in range(new_parts):
                measurement = metrics["cycle_time"]
                spc_monitor.add_measurement(measurement)

        spc_metrics = spc_monitor.get_metrics()
        machine_vars["spc_xbar_current"].set_value(spc_metrics.x_bar)
        machine_vars["spc_xbar_ucl"].set_value(spc_metrics.x_bar_ucl)
        machine_vars["spc_xbar_cl"].set_value(spc_metrics.x_bar_cl)
        machine_vars["spc_xbar_lcl"].set_value(spc_metrics.x_bar_lcl)

        machine_vars["spc_r_current"].set_value(spc_metrics.range)
        machine_vars["spc_r_ucl"].set_value(spc_metrics.r_ucl)
        machine_vars["spc_r_cl"].set_value(spc_metrics.r_cl)
        machine_vars["spc_r_lcl"].set_value(spc_metrics.r_lcl)

        machine_vars["spc_cp"].set_value(spc_metrics.cp)
        machine_vars["spc_cpk"].set_value(spc_metrics.cpk)
        machine_vars["spc_pp"].set_value(spc_metrics.pp)
        machine_vars["spc_ppk"].set_value(spc_metrics.ppk)
        machine_vars["spc_sigma_level"].set_value(spc_metrics.sigma_level)

        machine_vars["spc_in_control"].set_value(spc_metrics.in_control)
        violations_str = ", ".join(spc_metrics.violations) if spc_metrics.violations else ""
        machine_vars["spc_violations"].set_value(violations_str)
        machine_vars["spc_total_samples"].set_value(spc_metrics.total_samples)
        machine_vars["spc_num_subgroups"].set_value(spc_metrics.num_subgroups)

    # OEE
    machine_vars["availability"].set_value(oee_result["availability"])
    machine_vars["performance"].set_value(oee_result["performance"])
    machine_vars["quality"].set_value(oee_result["quality"])
    machine_vars["oee"].set_value(oee_result["oee"])
    machine_vars["good_parts"].set_value(oee_result["good_parts"])
    machine_vars["defective_parts"].set_value(oee_result["defective_parts"])
    machine_vars["theoretical"].set_value(oee_result["theoretical_output"])

    # Quality routing
    if isinstance(machine_obj, QualityRoutingMixin):
        if "qr_scrap_count" in machine_vars:
            machine_vars["qr_scrap_count"].set_value(machine_obj._scrap_count)
            machine_vars["qr_rework_count"].set_value(machine_obj._rework_count)
            machine_vars["qr_rework_success_count"].set_value(machine_obj._rework_success_count)
            rsr = (machine_obj._rework_success_count / machine_obj._rework_count
                   if machine_obj._rework_count > 0 else 0.0)
            machine_vars["qr_rework_success_rate"].set_value(rsr)
            machine_vars["qr_good_count"].set_value(machine_obj._good_count)


def update_buffers(buffers, opcua_vars):
    """Update buffer levels and detect buffer alarms.

    Returns:
        dict: buffer_alarms_map {buffer_name: [alarm_tuples]}
    """
    buffer_alarms_map = {}
    for buffer_name, buffer_obj in buffers.items():
        buffer_vars = opcua_vars["buffers"][buffer_name]
        buffer_vars["level"].set_value(buffer_obj.level)

        if not hasattr(buffer_obj, '_alarm_state'):
            buffer_obj._alarm_state = {}

        buffer_alarms = detect_buffer_alarms(
            buffer_name=buffer_name,
            buffer_level=buffer_obj.level,
            buffer_capacity=buffer_obj.capacity,
            alarm_state=buffer_obj._alarm_state
        )

        if buffer_alarms:
            update_alarm_variables(buffer_vars, buffer_alarms)
            buffer_alarms_map[buffer_name] = buffer_alarms

    return buffer_alarms_map


def update_scrap_tracking(scrap_sinks, total_parts_produced, opcua_vars):
    """Update scrap sink levels and compute scrap KPIs. Returns total_scrap."""
    total_scrap = 0
    for scrap_name, scrap_obj in scrap_sinks.items():
        scrap_level = scrap_obj.level
        total_scrap += scrap_level
        if scrap_name in opcua_vars["scrap_sinks"]:
            opcua_vars["scrap_sinks"][scrap_name]["level"].set_value(scrap_level)

    total_output = total_parts_produced + total_scrap
    opcua_vars["scrap_kpis"]["total_scrap"].set_value(total_scrap)
    opcua_vars["scrap_kpis"]["scrap_rate"].set_value(
        total_scrap / total_output if total_output > 0 else 0.0
    )
    return total_scrap


def calculate_line_level_oee(machines, machine_metrics):
    """Calculate line-level OEE using bottleneck model (minimum of all stations).

    Returns:
        tuple: (line_availability, line_performance, line_quality, line_oee)
    """
    all_oee_results = [
        calculate_oee(machine_metrics[m]["partcount"],
                      machine_metrics[m],
                      machine_metrics[m]["cycle_time"])
        for m in machines.keys()
    ]

    line_availability = min(r["availability"] for r in all_oee_results) if all_oee_results else 0.0
    line_performance = min(r["performance"] for r in all_oee_results) if all_oee_results else 0.0
    line_quality = min(r["quality"] for r in all_oee_results) if all_oee_results else 0.0
    line_oee = line_availability * line_performance * line_quality

    return line_availability, line_performance, line_quality, line_oee


def write_system_opcua_vars(opcua_vars, sim_time, total_parts_produced, total_wip,
                            line_availability, line_performance, line_quality, line_oee,
                            maint_active, maint_queue_length, total_repairs):
    """Write system-level and line-level KPIs to OPC UA."""
    opcua_vars["system"]["simtime"].set_value(sim_time)
    opcua_vars["system"]["throughput"].set_value(total_parts_produced)
    opcua_vars["line_kpis"]["total_wip"].set_value(total_wip)
    opcua_vars["line_kpis"]["line_availability"].set_value(line_availability)
    opcua_vars["line_kpis"]["line_performance"].set_value(line_performance)
    opcua_vars["line_kpis"]["line_quality"].set_value(line_quality)
    opcua_vars["line_kpis"]["line_oee"].set_value(line_oee)

    opcua_vars["maintenance"]["active"].set_value(maint_active)
    opcua_vars["maintenance"]["queue"].set_value(maint_queue_length)
    opcua_vars["maintenance"]["total_repairs"].set_value(total_repairs)


def update_shift_opcua_vars(shift_manager, opcua_vars, sim_time, delta_parts):
    """Update shift tracking metrics and OPC UA variables."""
    if not (shift_manager and opcua_vars.get("shift")):
        return

    shift_manager.update_production(delta_parts, 0)

    shift_info = shift_manager.get_current_shift_info()
    shift_metrics = shift_manager.get_current_shift_metrics()
    total_metrics = shift_manager.get_total_metrics()
    prev_shift = shift_manager.get_previous_shift_summary()

    sv = opcua_vars["shift"]
    sv["shift_number"].set_value(shift_info["shift_number"])
    sv["shift_name"].set_value(shift_info["shift_name"])
    sv["shift_start_time"].set_value(shift_info["shift_start_time"])
    sv["shift_end_time"].set_value(shift_info["shift_end_time"])
    sv["shift_duration"].set_value(shift_info["shift_duration"])
    sv["shift_elapsed"].set_value(shift_manager.get_shift_elapsed_time(sim_time))
    sv["shift_remaining"].set_value(shift_manager.get_shift_time_remaining(sim_time))

    sv["current_parts"].set_value(shift_metrics["parts_produced"])
    sv["current_good"].set_value(shift_metrics["good_parts"])
    sv["current_defects"].set_value(shift_metrics["defective_parts"])
    sv["current_defect_rate"].set_value(shift_metrics["defect_rate"])
    sv["current_availability"].set_value(shift_metrics["availability"])
    sv["current_performance"].set_value(shift_metrics["performance"])
    sv["current_quality"].set_value(shift_metrics["quality"])
    sv["current_oee"].set_value(shift_metrics["oee"])

    if prev_shift:
        sv["prev_shift_number"].set_value(prev_shift["shift_number"])
        sv["prev_shift_name"].set_value(prev_shift["shift_name"])
        sv["prev_parts"].set_value(prev_shift["parts_produced"])
        sv["prev_good"].set_value(prev_shift["good_parts"])
        sv["prev_defects"].set_value(prev_shift["defective_parts"])
        sv["prev_defect_rate"].set_value(prev_shift["defect_rate"])
        sv["prev_oee"].set_value(prev_shift["oee"])

    sv["total_parts"].set_value(total_metrics["total_parts_produced"])
    sv["total_good"].set_value(total_metrics["total_good_parts"])
    sv["total_defects"].set_value(total_metrics["total_defective_parts"])
    sv["total_defect_rate"].set_value(total_metrics["total_defect_rate"])
    sv["total_shifts"].set_value(total_metrics["total_shifts_completed"])


def record_historian_events(historian, neo4j_hist, sim_time, machines, machine_metrics,
                            buffers, machine_alarms_map, buffer_alarms_map, shift_manager,
                            shift_rotated, spc_monitors, historian_state, config,
                            total_parts_produced, total_wip, line_oee, delta_parts,
                            production_summary_counter, production_summary_interval, sim_step):
    """Collect and record historian events. Returns updated production_summary_counter."""
    if not historian:
        return production_summary_counter

    step_events = collect_step_events(
        sim_time=sim_time,
        machines=machines,
        machine_metrics=machine_metrics,
        buffers=buffers,
        machine_alarms_map=machine_alarms_map,
        buffer_alarms_map=buffer_alarms_map,
        shift_manager=shift_manager,
        shift_rotated=shift_rotated,
        spc_monitors=spc_monitors,
        historian_state=historian_state,
        config=config,
    )

    if config.get("historian", {}).get("events", {}).get("production_summary", True):
        production_summary_counter += sim_step
        if production_summary_counter >= production_summary_interval:
            step_events.append(collect_production_summary(
                sim_time=sim_time,
                total_parts_produced=total_parts_produced,
                total_wip=total_wip,
                line_oee=line_oee,
                shift_manager=shift_manager,
            ))
            production_summary_counter = 0.0

    if step_events:
        historian.record_events(step_events)
        if neo4j_hist:
            neo4j_hist.record_events(step_events)

    if neo4j_hist and delta_parts > 0:
        machine_name_list = list(machines.keys())
        neo4j_hist.record_parts(
            delta_parts=delta_parts,
            machine_names=machine_name_list,
            defective_count=0,
            sim_time=sim_time,
        )

    return production_summary_counter


# ========== SYSTEM BUILDING ==========

def build_simantha_system(config: dict):
    """
    Build Simantha system from configuration.

    Args:
        config: Dict with keys 'machines', 'buffers', 'maintainer'

    Returns:
        tuple: (system, source, sink, machines_dict, buffers_dict, maintainer, scrap_sinks)
               machines_dict: {"M1": machine_obj, "M2": machine_obj, ...}
               buffers_dict: {"B1": buffer_obj, "B2": buffer_obj, ...}
               scrap_sinks: {"ScrapBin1": sink_obj, ...} (Phase 14, empty if none)
    """
    source = Source()
    sink = Sink(collect_parts=True)

    # Phase 14: Create scrap sinks
    scrap_sinks = {}
    for scrap_cfg in config.get("scrap_sinks", []):
        scrap_sinks[scrap_cfg["name"]] = Sink(
            name=scrap_cfg["name"], collect_parts=True
        )

    # Create machines from config
    machines = {}
    for machine_cfg in config["machines"]:
        name = machine_cfg["name"]
        cycle_time = int(machine_cfg.get("cycle_time", 1))  # Convert to int for Simantha
        enable_advanced_failures = machine_cfg.get("enable_advanced_failures", False)
        enable_degradation = machine_cfg.get("enable_degradation", False)

        # Phase 14: Check for quality routing
        quality_cfg = machine_cfg.get("quality_routing", {})
        has_quality_routing = quality_cfg.get("enabled", False)

        # Build degradation kwargs (shared across machine types)
        degradation_kwargs = {}
        if enable_degradation:
            degradation_kwargs["degradation_matrix"] = machine_cfg.get(
                "degradation_matrix", DEGRADATION_MATRIX
            )
            degradation_kwargs["cbm_threshold"] = machine_cfg.get("cbm_threshold", 1)

        # Build quality routing kwargs
        quality_kwargs = {}
        if has_quality_routing:
            quality_kwargs = {
                "defect_rate": quality_cfg.get("defect_rate", 0.0),
                "health_multiplier": quality_cfg.get("health_multiplier", 3.0),
                "enable_health_correlation": quality_cfg.get("enable_health_correlation", False),
                "rework_enabled": quality_cfg.get("mode", "scrap") in ("rework", "scrap_and_rework"),
                "rework_success_rate": quality_cfg.get("rework_success_rate", 0.8),
                "max_rework": quality_cfg.get("max_rework", 3),
            }

        # Build advanced failure kwargs (shared across AdvancedMachine variants)
        advanced_kwargs = {}
        if enable_advanced_failures:
            failure_modes = [
                FailureMode(
                    name=fm_cfg["name"],
                    type=fm_cfg["type"],
                    mttf_config=fm_cfg["mttf"],
                    mttr_config=fm_cfg["mttr"]
                )
                for fm_cfg in machine_cfg.get("failure_modes", [])
            ]
            strategy_cfg = machine_cfg.get("maintenance_strategy", {"type": "corrective"})
            advanced_kwargs = {"failure_modes": failure_modes, "maintenance_strategy": strategy_cfg}

        # Select machine class based on feature axes
        if enable_advanced_failures and has_quality_routing:
            machine_cls = QualityAdvancedMachine
        elif enable_advanced_failures:
            machine_cls = AdvancedMachine
        elif has_quality_routing:
            machine_cls = QualityAwareMachine
        else:
            machine_cls = Machine

        machines[name] = machine_cls(
            name=name,
            cycle_time=cycle_time,
            **advanced_kwargs,
            **quality_kwargs,
            **degradation_kwargs
        )

    # Phase 14: Wire scrap sinks to machines (after all objects created)
    for machine_cfg in config["machines"]:
        quality_cfg = machine_cfg.get("quality_routing", {})
        if quality_cfg.get("enabled", False):
            scrap_name = quality_cfg.get("scrap_sink")
            if scrap_name and scrap_name in scrap_sinks:
                machines[machine_cfg["name"]].set_scrap_sink(scrap_sinks[scrap_name])

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

    # Create System (include scrap sinks so they get env reference)
    all_objects = [source] + machine_list + buffer_list + [sink] + list(scrap_sinks.values())
    if maintainer is not None:
        system = System(objects=all_objects, maintainer=maintainer)
    else:
        system = System(objects=all_objects)

    return system, source, sink, machines, buffers, maintainer, scrap_sinks


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

    # Phase 14: Line-level scrap KPIs
    var_total_scrap = line_kpi_node.add_variable(idx, "TotalScrap", 0)
    var_scrap_rate = line_kpi_node.add_variable(idx, "ScrapRate", 0.0)

    # Phase 9b: EventLog node (optional - for future event generation)
    event_log_node = line1.add_object(idx, "EventLog")
    var_total_events = event_log_node.add_variable(idx, "TotalEventsGenerated", 0)

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

        # Phase 10: Check for advanced failures
        enable_failure_modes = machine_cfg.get("enable_advanced_failures", False)
        failure_mode_names = []
        if enable_failure_modes:
            failure_mode_names = [fm["name"] for fm in machine_cfg.get("failure_modes", [])]

        # Phase 11: Check for SPC analytics
        enable_spc = machine_cfg.get("enable_spc", False)

        # Phase 14: Check for quality routing
        enable_quality_routing = machine_cfg.get("quality_routing", {}).get("enabled", False)

        station_vars = create_station_node(line1, idx, station_name, enable_health,
                                          enable_failure_modes, failure_mode_names,
                                          enable_spc, enable_quality_routing)
        machines_vars[machine_name] = station_vars

    # Phase 14: Scrap sink OPC UA nodes
    scrap_vars = {}
    for scrap_cfg in config.get("scrap_sinks", []):
        scrap_name = scrap_cfg["name"]
        scrap_node = line1.add_object(idx, scrap_name)
        scrap_vars[scrap_name] = {
            "level": scrap_node.add_variable(idx, "CurrentLevel", 0),
        }

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

    # Phase 12: Shift tracking (optional)
    shift_vars = {}
    if "shifts" in config:
        shift_vars = create_shift_node(line1, idx)

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
        },
        "shift": shift_vars,  # Phase 12: Shift tracking
        "scrap_sinks": scrap_vars,  # Phase 14: Scrap sink nodes
        "scrap_kpis": {
            "total_scrap": var_total_scrap,
            "scrap_rate": var_scrap_rate,
        },
    }

    return server, opcua_vars, idx


def main(argv=None):
    import argparse
    import random

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Simantha OPC UA Server")
    parser.add_argument("--scenario", default="balanced_line",
                       help="Scenario name from line_models.yaml (default: balanced_line)")
    parser.add_argument("--seed", type=int, default=None,
                       help="Random seed for reproducible defect generation (Phase 8)")
    args = parser.parse_args(argv)

    # Set random seed if provided (Phase 8)
    if args.seed is not None:
        random.seed(args.seed)
        print(f"Using random seed: {args.seed}")

    # Load configuration
    config = load_line_config(args.scenario)
    print(f"Loading scenario: {args.scenario}")

    # Build Simantha system from config
    system, source, sink, machines, buffers, maintainer, scrap_sinks = build_simantha_system(config)

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

    # Phase 11: SPC monitors for machines with enable_spc=True
    spc_monitors = {}

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

            # Phase 9: Alarm state tracking
            "prev_health_state": 0,
            "prev_maint_active": False,
            "prev_defect_rate": 0.0,
            "alarm_machine_failed_active": False,
            "alarm_maintenance_active": False,
            "alarm_quality_alert_active": False,
        }

        # Phase 11: Create SPC monitor if enabled
        if machine_cfg.get("enable_spc", False):
            spc_config_dict = machine_cfg.get("spc", {})
            spc_config = SPCConfiguration(
                subgroup_size=spc_config_dict.get("subgroup_size", 5),
                num_subgroups=spc_config_dict.get("num_subgroups", 25),
                usl=spc_config_dict.get("usl", None),
                lsl=spc_config_dict.get("lsl", None),
                target=spc_config_dict.get("target", None),
                enable_western_electric=spc_config_dict.get("enable_western_electric", True),
                characteristic=spc_config_dict.get("characteristic", "cycle_time")
            )
            spc_monitors[machine_name] = ProcessMonitor(spc_config)
            print(f"  SPC enabled for {machine_name}: {spc_config.characteristic} (USL={spc_config.usl}, LSL={spc_config.lsl})")

    # Phase 12: Create shift manager if configured
    shift_manager = create_shift_manager_from_config(config, list(machines.keys()))
    if shift_manager:
        print(f"  Shift tracking enabled: {len(shift_manager.shift_definitions)} shifts")
        for i, shift_def in enumerate(shift_manager.shift_definitions):
            print(f"    Shift {i+1}: {shift_def.name} ({shift_def.duration} time units)")

    # Phase 13: Create event historian if configured
    historian = create_historian_from_config(config, args.scenario)
    historian_state = {}  # Separate edge-detection state for historian
    production_summary_counter = 0.0
    production_summary_interval = config.get("historian", {}).get("events", {}).get("production_summary_interval", 60)
    if historian:
        print(f"  Event historian enabled: {historian.describe()}")

    # Phase 13c: Create Neo4j historian if configured
    neo4j_hist = create_neo4j_historian_from_config(config, args.scenario)
    if neo4j_hist:
        neo4j_hist.create_topology(config)
        print(f"  Neo4j historian enabled: {neo4j_hist.describe()}")

    server.start()
    print(f"OPC UA server started at opc.tcp://localhost:4840/simantha/")
    print(f"Scenario: {args.scenario} ({len(machines)} machines, {len(buffers)} buffers)")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            # Read controls from OPC UA
            pause_line, interarrival = read_opcua_controls(opcua_vars)
            source.interarrival_time = interarrival

            # Step simulation (CRITICAL: increment sim_time BEFORE simulate)
            if not pause_line:
                sim_time += sim_step
                system.simulate(simulation_time=sim_time)

            # Monotonic part counter (handles sink.level decreasing during maintenance)
            delta_parts, total_parts_produced, prev_sink_level = update_part_counter(
                sink.level, prev_sink_level, total_parts_produced)

            # Shift rotation check
            shift_rotated = check_shift_rotation(shift_manager, sim_time, pause_line)

            # System-level metrics (WIP, maintenance)
            total_wip, maint_active, maint_queue_length, total_repairs = \
                collect_system_metrics(buffers, maintainer)

            # Per-machine: state detection, metrics, defects, alarms, OEE, SPC, OPC UA writes
            machine_alarms_map = {}
            for machine_name, machine_obj in machines.items():
                alarms = process_machine_step(
                    machine_name, machine_obj, machine_metrics[machine_name],
                    config["machines"], total_parts_produced, pause_line, sim_step,
                    maintainer, shift_manager, spc_monitors, opcua_vars, sink)
                if alarms:
                    machine_alarms_map[machine_name] = alarms

            # Buffer levels and alarms
            buffer_alarms_map = update_buffers(buffers, opcua_vars)

            # Scrap tracking
            update_scrap_tracking(scrap_sinks, total_parts_produced, opcua_vars)

            # Line-level OEE (bottleneck model)
            line_avail, line_perf, line_qual, line_oee = \
                calculate_line_level_oee(machines, machine_metrics)

            # Write system KPIs to OPC UA
            write_system_opcua_vars(opcua_vars, sim_time, total_parts_produced, total_wip,
                                    line_avail, line_perf, line_qual, line_oee,
                                    maint_active, maint_queue_length, total_repairs)

            # Shift OPC UA updates
            update_shift_opcua_vars(shift_manager, opcua_vars, sim_time, delta_parts)

            # Historian events
            production_summary_counter = record_historian_events(
                historian, neo4j_hist, sim_time, machines, machine_metrics,
                buffers, machine_alarms_map, buffer_alarms_map, shift_manager,
                shift_rotated, spc_monitors, historian_state, config,
                total_parts_produced, total_wip, line_oee, delta_parts,
                production_summary_counter, production_summary_interval, sim_step)

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
        # Phase 13: Flush and close historians
        if historian:
            historian.flush()
            historian.close()
            print(f"Event historian closed ({historian.event_count} events recorded)")
        if neo4j_hist:
            neo4j_hist.close()
            print(f"Neo4j historian closed ({neo4j_hist.event_count} events, {neo4j_hist._part_counter} parts)")
        server.stop()
        print("Server stopped.")


if __name__ == "__main__":
    main()
