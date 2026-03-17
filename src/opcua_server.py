import logging
import os
import random
import sys
import time
import traceback
from collections import Counter
from datetime import datetime

# Suppress noisy OPC UA library warnings
logging.getLogger("opcua").setLevel(logging.WARNING)
logging.getLogger("opcua.server.internal_server").setLevel(logging.ERROR)
logging.getLogger("opcua.server.address_space").setLevel(logging.ERROR)

from opcua import Server, ua
from simantha import Source, Machine, Buffer, Sink, System, Maintainer
from simantha.simulation import Environment

from line_state import LineState


# Monkey-patch Simantha's Environment.step() to print actual tracebacks
# instead of swallowing exceptions with a bare except:
_original_step = Environment.step


def _patched_step(self):
    next_event = self.events.pop(0)
    self.now = next_event.time

    try:
        if self.trace:
            self.trace_event(next_event)
        next_event.execute()
    except Exception as e:
        self.export_trace()
        print('Failed event:')
        print(f'  time:      {next_event.time}')
        print(f'  location:  {next_event.location}')
        print(f'  action:    {next_event.action.__name__}')
        print(f'  priority:  {next_event.priority}')
        print(f'  exception: {type(e).__name__}: {e}')
        traceback.print_exc()
        # Dump machine state for debugging
        for obj in getattr(self, 'objects', []):
            if hasattr(obj, 'has_part'):
                print(f'  {obj.name}: has_part={obj.has_part} contents={len(obj.contents)} '
                      f'failed={getattr(obj, "failed", "?")} '
                      f'blocked={obj.blocked} starved={obj.starved} '
                      f'target_receiver={getattr(obj.target_receiver, "name", None)}')
            elif hasattr(obj, 'level'):
                rv = getattr(obj, 'reserved_vacancy', 'N/A')
                rc = getattr(obj, 'reserved_content', 'N/A')
                print(f'  {obj.name}: level={obj.level} reserved_vacancy={rv} '
                      f'reserved_content={rc}')
        sys.exit(1)


Environment.step = _patched_step


# Monkey-patch Simantha's Sink.initialize() to reset level_data.
# Bug: Buffer and Machine reset their data lists in initialize(), but Sink does not.
# Since system.simulate(N) calls initialize() then runs 0..N each step, Sink.level_data
# grows quadratically (K*(K+1)/2 entries after K steps) and causes MemoryError.
_original_sink_initialize = Sink.initialize


def _patched_sink_initialize(self):
    _original_sink_initialize(self)
    self.level_data = {'time': [0], 'level': [self.initial_level]}


Sink.initialize = _patched_sink_initialize


# Monkey-patch python-opcua Bug #848: ReferenceTypeAttributes defaults.
# python-opcua sets IsAbstract=True and Symmetric=True by default for all
# ReferenceType nodes. The OPC UA spec requires concrete reference types
# (Organizes, HasSubtype, HasComponent, HasProperty) to have IsAbstract=False
# and Symmetric=False. Industrial clients like FactoryTalk Optix refuse to use
# reference types marked as abstract, causing "Type 0/35 not found" errors and
# preventing type tree traversal.
# See: https://github.com/FreeOpcUa/python-opcua/issues/848
_original_reftype_init = ua.uaprotocol_auto.ReferenceTypeAttributes.__init__


def _patched_reftype_init(self):
    _original_reftype_init(self)
    self.IsAbstract = False
    self.Symmetric = False


ua.uaprotocol_auto.ReferenceTypeAttributes.__init__ = _patched_reftype_init


# Monkey-patch python-opcua Bug: ViewService._suitable_reftype blocks
# HasSubtype references when includeSubtypes=False. This prevents clients from
# browsing the DataType/VariableType hierarchy, causing "Data type 0/12 not
# found" errors for every variable. Industrial clients like FactoryTalk Optix
# browse with includeSubtypes=False expecting to get HasSubtype references.
# See: https://github.com/FreeOpcUa/opcua-asyncio/issues/233
from opcua.server.address_space import ViewService as _ViewService


def _patched_suitable_reftype(self, ref1, ref2, subtypes):
    if ref1 == ua.NodeId(ua.ObjectIds.Null):
        return True
    if ref1.Identifier == ref2.Identifier:
        return True
    if subtypes:
        oktypes = self._get_sub_ref(ref1)
        return ref2 in oktypes
    return False


_ViewService._suitable_reftype = _patched_suitable_reftype


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



# ========== HELPER FUNCTIONS ==========


def _nid(path, idx):
    """Create an explicit string NodeId from a dot-separated path.

    Gives every OPC UA node a stable, human-readable identifier like
    ``ns=2;s=Line1.Machine1.OEE.OEE`` instead of an auto-generated numeric id.
    """
    return ua.NodeId(path, idx)


def _qn(name, idx):
    """Create a QualifiedName with the correct namespace for BrowseName.

    When passing a NodeId (not an int) as the first arg to add_object/add_variable,
    python-opcua defaults the BrowseName namespace to 0. This helper ensures the
    BrowseName uses the correct application namespace so that get_child("2:Name")
    navigation works for OPC UA clients.
    """
    return ua.QualifiedName(name, idx)


def create_machine_node(parent_node, opcua_idx: int, machine_node_name: str, enable_health: bool = False,
                        enable_failure_modes: bool = False, failure_mode_names: list = None,
                        enable_spc: bool = False, enable_quality_routing: bool = False,
                        node_prefix: str = ""):
    """
    Create ISA-95 aligned OPC UA variables for a single machine (Equipment node).

    Internal structure follows ISA-95 grouping:
      M{i}_Equipment/
        Identification/       EquipmentID, EquipmentClass, Description
        OperationsState/      State, HealthState, HealthPercent
        OperationsPerformance/ PartCount, Utilisation, TargetPPM, ActualPPM, *Time
        OEE/                  Availability, Performance, Quality, OEE, GoodPartCount, ...
        Alarms/               ActiveAlarmCount, MachineFailureActive, ...
        FailureModes/         (optional)
        MaintenanceStrategy/  (optional)
        SPC/                  (optional)
        QualityRouting/       (optional)

    Args:
        parent_node: Parent OPC UA node (Resources object)
        opcua_idx: OPC UA namespace index
        machine_node_name: Equipment BrowseName (e.g., "M1_Equipment")
        enable_health: Whether to create health variables
        enable_failure_modes: Whether to create FailureModes/MaintenanceStrategy subnodes
        failure_mode_names: List of failure mode names (e.g., ["mechanical", "electrical"])
        enable_spc: Whether to create SPC subnode
        enable_quality_routing: Whether to create QualityRouting subnode
        node_prefix: Dot-separated prefix for explicit NodeIds

    Returns:
        dict: Dictionary of variable objects
    """
    p = node_prefix  # shorthand
    machine_node = parent_node.add_object(_nid(p, opcua_idx), _qn(machine_node_name, opcua_idx))

    vars_dict = {}

    # --- Identification ---
    id_p = f"{p}.Identification"
    id_node = machine_node.add_object(_nid(id_p, opcua_idx), _qn("Identification", opcua_idx))
    # Extract short id like "M1" from "M1_Equipment"
    short_id = machine_node_name.replace("_Equipment", "")
    id_node.add_variable(_nid(f"{id_p}.EquipmentID", opcua_idx), _qn("EquipmentID", opcua_idx), short_id)
    id_node.add_variable(_nid(f"{id_p}.EquipmentClass", opcua_idx), _qn("EquipmentClass", opcua_idx), "WorkCell")
    id_node.add_variable(_nid(f"{id_p}.Description", opcua_idx), _qn("Description", opcua_idx), f"Machine {short_id}")

    # --- OperationsState (State + Health) ---
    os_p = f"{p}.OperationsState"
    ops_state_node = machine_node.add_object(_nid(os_p, opcua_idx), _qn("OperationsState", opcua_idx))
    vars_dict["state"] = ops_state_node.add_variable(_nid(f"{os_p}.State", opcua_idx), _qn("State", opcua_idx), "IDLE")

    if enable_health:
        vars_dict["health"] = ops_state_node.add_variable(_nid(f"{os_p}.HealthState", opcua_idx), _qn("HealthState", opcua_idx), 0)
        vars_dict["health_pct"] = ops_state_node.add_variable(_nid(f"{os_p}.HealthPercent", opcua_idx), _qn("HealthPercent", opcua_idx), 100.0)

    # --- OperationsPerformance (counts + time tracking) ---
    op_p = f"{p}.OperationsPerformance"
    ops_perf_node = machine_node.add_object(_nid(op_p, opcua_idx), _qn("OperationsPerformance", opcua_idx))
    vars_dict["partcount"] = ops_perf_node.add_variable(_nid(f"{op_p}.PartCount", opcua_idx), _qn("PartCount", opcua_idx), 0)
    vars_dict["utilisation"] = ops_perf_node.add_variable(_nid(f"{op_p}.Utilisation", opcua_idx), _qn("Utilisation", opcua_idx), 0.0)
    vars_dict["target_ppm"] = ops_perf_node.add_variable(_nid(f"{op_p}.TargetPPM", opcua_idx), _qn("TargetPPM", opcua_idx), 0.0)
    vars_dict["actual_ppm"] = ops_perf_node.add_variable(_nid(f"{op_p}.ActualPPM", opcua_idx), _qn("ActualPPM", opcua_idx), 0.0)
    vars_dict["blocked_time"] = ops_perf_node.add_variable(_nid(f"{op_p}.BlockedTime", opcua_idx), _qn("BlockedTime", opcua_idx), 0.0)
    vars_dict["starved_time"] = ops_perf_node.add_variable(_nid(f"{op_p}.StarvedTime", opcua_idx), _qn("StarvedTime", opcua_idx), 0.0)
    vars_dict["down_time"] = ops_perf_node.add_variable(_nid(f"{op_p}.DownTime", opcua_idx), _qn("DownTime", opcua_idx), 0.0)
    vars_dict["processing_time"] = ops_perf_node.add_variable(_nid(f"{op_p}.ProcessingTime", opcua_idx), _qn("ProcessingTime", opcua_idx), 0.0)
    vars_dict["idle_time"] = ops_perf_node.add_variable(_nid(f"{op_p}.IdleTime", opcua_idx), _qn("IdleTime", opcua_idx), 0.0)

    # --- OEE sub-node (7 variables) ---
    oee_p = f"{p}.OEE"
    oee_node = machine_node.add_object(_nid(oee_p, opcua_idx), _qn("OEE", opcua_idx))
    vars_dict["availability"] = oee_node.add_variable(_nid(f"{oee_p}.Availability", opcua_idx), _qn("Availability", opcua_idx), 0.0)
    vars_dict["performance"] = oee_node.add_variable(_nid(f"{oee_p}.Performance", opcua_idx), _qn("Performance", opcua_idx), 0.0)
    vars_dict["quality"] = oee_node.add_variable(_nid(f"{oee_p}.Quality", opcua_idx), _qn("Quality", opcua_idx), 1.0)
    vars_dict["oee"] = oee_node.add_variable(_nid(f"{oee_p}.OEE", opcua_idx), _qn("OEE", opcua_idx), 0.0)
    vars_dict["good_parts"] = oee_node.add_variable(_nid(f"{oee_p}.GoodPartCount", opcua_idx), _qn("GoodPartCount", opcua_idx), 0)
    vars_dict["defective_parts"] = oee_node.add_variable(_nid(f"{oee_p}.DefectivePartCount", opcua_idx), _qn("DefectivePartCount", opcua_idx), 0)
    vars_dict["theoretical"] = oee_node.add_variable(_nid(f"{oee_p}.TheoreticalOutput", opcua_idx), _qn("TheoreticalOutput", opcua_idx), 0.0)

    # --- Alarms sub-node ---
    alarm_vars = create_alarms_node(machine_node, opcua_idx, alarm_type="machine",
                                    node_prefix=f"{p}.Alarms")
    vars_dict.update({f"alarm_{k}": v for k, v in alarm_vars.items()})

    # --- FailureModes sub-node (optional) ---
    if enable_failure_modes and failure_mode_names:
        fm_p = f"{p}.FailureModes"
        fm_node = machine_node.add_object(_nid(fm_p, opcua_idx), _qn("FailureModes", opcua_idx))
        vars_dict["fm_active"] = fm_node.add_variable(_nid(f"{fm_p}.ActiveFailureMode", opcua_idx), _qn("ActiveFailureMode", opcua_idx), "none")

        for fm_name in failure_mode_names:
            prefix = fm_name.capitalize()
            vars_dict[f"fm_{fm_name}_count"] = fm_node.add_variable(_nid(f"{fm_p}.{prefix}FailureCount", opcua_idx), _qn(f"{prefix}FailureCount", opcua_idx), 0)
            vars_dict[f"fm_{fm_name}_downtime"] = fm_node.add_variable(_nid(f"{fm_p}.{prefix}TotalDowntime", opcua_idx), _qn(f"{prefix}TotalDowntime", opcua_idx), 0.0)
            vars_dict[f"fm_{fm_name}_mtbf"] = fm_node.add_variable(_nid(f"{fm_p}.{prefix}MTBF", opcua_idx), _qn(f"{prefix}MTBF", opcua_idx), 0.0)
            vars_dict[f"fm_{fm_name}_mttr"] = fm_node.add_variable(_nid(f"{fm_p}.{prefix}MTTR", opcua_idx), _qn(f"{prefix}MTTR", opcua_idx), 0.0)

        # MaintenanceStrategy sub-node
        ms_p = f"{p}.MaintenanceStrategy"
        ms_node = machine_node.add_object(_nid(ms_p, opcua_idx), _qn("MaintenanceStrategy", opcua_idx))
        vars_dict["ms_type"] = ms_node.add_variable(_nid(f"{ms_p}.StrategyType", opcua_idx), _qn("StrategyType", opcua_idx), "corrective")
        vars_dict["ms_next_pm"] = ms_node.add_variable(_nid(f"{ms_p}.NextPMScheduled", opcua_idx), _qn("NextPMScheduled", opcua_idx), -1.0)
        vars_dict["ms_pm_count"] = ms_node.add_variable(_nid(f"{ms_p}.PMCount", opcua_idx), _qn("PMCount", opcua_idx), 0)
        vars_dict["ms_cm_count"] = ms_node.add_variable(_nid(f"{ms_p}.CMCount", opcua_idx), _qn("CMCount", opcua_idx), 0)

    # --- SPC sub-node (optional) ---
    if enable_spc:
        spc_vars = create_spc_node(machine_node, opcua_idx, machine_prefix=machine_node_name,
                                   node_prefix=f"{p}.SPC")
        vars_dict.update({f"spc_{k}": v for k, v in spc_vars.items()})

    # --- QualityRouting sub-node (optional) ---
    if enable_quality_routing:
        qr_p = f"{p}.QualityRouting"
        qr_node = machine_node.add_object(_nid(qr_p, opcua_idx), _qn("QualityRouting", opcua_idx))
        vars_dict["qr_scrap_count"] = qr_node.add_variable(_nid(f"{qr_p}.ScrapCount", opcua_idx), _qn("ScrapCount", opcua_idx), 0)
        vars_dict["qr_rework_count"] = qr_node.add_variable(_nid(f"{qr_p}.ReworkCount", opcua_idx), _qn("ReworkCount", opcua_idx), 0)
        vars_dict["qr_rework_success_count"] = qr_node.add_variable(_nid(f"{qr_p}.ReworkSuccessCount", opcua_idx), _qn("ReworkSuccessCount", opcua_idx), 0)
        vars_dict["qr_rework_success_rate"] = qr_node.add_variable(_nid(f"{qr_p}.ReworkSuccessRate", opcua_idx), _qn("ReworkSuccessRate", opcua_idx), 0.0)
        vars_dict["qr_good_count"] = qr_node.add_variable(_nid(f"{qr_p}.GoodCount", opcua_idx), _qn("GoodCount", opcua_idx), 0)

    return vars_dict


def create_machine_asset_node(parent_node, opcua_idx: int, asset_node_name: str,
                              node_prefix: str = ""):
    """
    Create ISA-95 PhysicalAsset node for a machine (M{i}_Asset).

    Contains identification metadata (vendor, model, serial) — static values
    set at startup. No runtime updates needed.

    Args:
        parent_node: Parent OPC UA node (Resources object)
        opcua_idx: OPC UA namespace index
        asset_node_name: Asset BrowseName (e.g., "M1_Asset")
        node_prefix: Dot-separated prefix for explicit NodeIds

    Returns:
        dict: Dictionary of asset variable objects (informational only)
    """
    p = node_prefix
    asset_node = parent_node.add_object(_nid(p, opcua_idx), _qn(asset_node_name, opcua_idx))

    id_p = f"{p}.Identification"
    id_node = asset_node.add_object(_nid(id_p, opcua_idx), _qn("Identification", opcua_idx))

    short_id = asset_node_name.replace("_Asset", "")
    id_node.add_variable(_nid(f"{id_p}.PhysicalAssetID", opcua_idx), _qn("PhysicalAssetID", opcua_idx), asset_node_name)
    id_node.add_variable(_nid(f"{id_p}.AssetClass", opcua_idx), _qn("AssetClass", opcua_idx), "Machine")
    id_node.add_variable(_nid(f"{id_p}.Vendor", opcua_idx), _qn("Vendor", opcua_idx), "Generic")
    id_node.add_variable(_nid(f"{id_p}.Model", opcua_idx), _qn("Model", opcua_idx), "StandardMachine")
    id_node.add_variable(_nid(f"{id_p}.SerialNumber", opcua_idx), _qn("SerialNumber", opcua_idx), f"SN-{short_id}-001")

    return {}


def create_storage_unit_node(parent_node, opcua_idx: int, unit_name: str, capacity: int,
                             node_prefix: str = "", include_alarms: bool = True):
    """
    Create ISA-95 StorageUnit node for a buffer or scrap bin.

    Args:
        parent_node: Parent OPC UA node (Resources object)
        opcua_idx: OPC UA namespace index
        unit_name: StorageUnit BrowseName (e.g., "B1_StorageUnit", "ScrapBin1_StorageUnit")
        capacity: Storage capacity (-1 for unlimited/scrap)
        node_prefix: Dot-separated prefix for explicit NodeIds
        include_alarms: Whether to create Alarms sub-node (True for buffers, False for scrap)

    Returns:
        dict: Dictionary of variable objects
    """
    p = node_prefix
    unit_node = parent_node.add_object(_nid(p, opcua_idx), _qn(unit_name, opcua_idx))

    vars_dict = {}
    vars_dict["level"] = unit_node.add_variable(_nid(f"{p}.CurrentLevel", opcua_idx), _qn("CurrentLevel", opcua_idx), 0)
    if capacity >= 0:
        vars_dict["capacity"] = unit_node.add_variable(_nid(f"{p}.Capacity", opcua_idx), _qn("Capacity", opcua_idx), capacity)

    if include_alarms:
        alarm_vars = create_alarms_node(unit_node, opcua_idx, alarm_type="buffer",
                                        node_prefix=f"{p}.Alarms")
        vars_dict.update({f"alarm_{k}": v for k, v in alarm_vars.items()})

    return vars_dict


def create_alarms_node(parent_node, opcua_idx: int, alarm_type: str = "machine",
                       node_prefix: str = ""):
    """
    Create Alarms sub-node for a machine or buffer.

    Args:
        parent_node: Parent OPC UA node (machine or buffer)
        opcua_idx: OPC UA namespace index
        alarm_type: "machine" or "buffer"
        node_prefix: Dot-separated prefix for explicit NodeIds (e.g., "Line1.Machine1.Alarms")

    Returns:
        dict: Dictionary of alarm variable objects
    """
    p = node_prefix
    alarms_node = parent_node.add_object(_nid(p, opcua_idx), _qn("Alarms", opcua_idx))

    vars_dict = {}
    vars_dict["alarm_count"] = alarms_node.add_variable(_nid(f"{p}.ActiveAlarmCount", opcua_idx), _qn("ActiveAlarmCount", opcua_idx), 0)
    vars_dict["last_alarm_time"] = alarms_node.add_variable(_nid(f"{p}.LastAlarmTime", opcua_idx), _qn("LastAlarmTime", opcua_idx), datetime.now())
    vars_dict["last_alarm_message"] = alarms_node.add_variable(_nid(f"{p}.LastAlarmMessage", opcua_idx), _qn("LastAlarmMessage", opcua_idx), "")
    vars_dict["last_alarm_severity"] = alarms_node.add_variable(_nid(f"{p}.LastAlarmSeverity", opcua_idx), _qn("LastAlarmSeverity", opcua_idx), "")

    if alarm_type == "machine":
        vars_dict["alarm_failure"] = alarms_node.add_variable(_nid(f"{p}.MachineFailureActive", opcua_idx), _qn("MachineFailureActive", opcua_idx), False)
        vars_dict["alarm_maintenance"] = alarms_node.add_variable(_nid(f"{p}.MaintenanceActive", opcua_idx), _qn("MaintenanceActive", opcua_idx), False)
        vars_dict["alarm_quality"] = alarms_node.add_variable(_nid(f"{p}.QualityAlertActive", opcua_idx), _qn("QualityAlertActive", opcua_idx), False)
    elif alarm_type == "buffer":
        vars_dict["alarm_high"] = alarms_node.add_variable(_nid(f"{p}.HighLevelWarningActive", opcua_idx), _qn("HighLevelWarningActive", opcua_idx), False)
        vars_dict["alarm_low"] = alarms_node.add_variable(_nid(f"{p}.LowLevelWarningActive", opcua_idx), _qn("LowLevelWarningActive", opcua_idx), False)

    return vars_dict


def _add_prefixed_var(parent, idx, browse_name, default_val, display_prefix, nid_path=""):
    """Add an OPC UA variable with a prefixed DisplayName for clarity in UA browsers.

    BrowseName remains unchanged (e.g. "Cp") for backward-compatible path navigation.
    DisplayName becomes e.g. "Machine1_Cp" so it's unambiguous in flat views.
    """
    if nid_path:
        v = parent.add_variable(_nid(nid_path, idx), _qn(browse_name, idx), default_val)
    else:
        v = parent.add_variable(idx, browse_name, default_val)
    if display_prefix:
        v.set_attribute(
            ua.AttributeIds.DisplayName,
            ua.DataValue(ua.LocalizedText(f"{display_prefix}_{browse_name}"))
        )
    return v


def create_spc_node(parent_node, opcua_idx: int, machine_prefix: str = "",
                    node_prefix: str = ""):
    """
    Create SPC (Statistical Process Control) sub-node for a machine.

    Args:
        parent_node: Parent OPC UA node (machine)
        opcua_idx: OPC UA namespace index
        machine_prefix: Prefix for DisplayName (e.g. "Machine1")
        node_prefix: Dot-separated prefix for explicit NodeIds (e.g., "Line1.Machine1.SPC")

    Returns:
        dict: Dictionary of SPC variable objects
    """
    np_ = node_prefix  # shorthand (avoid shadowing numpy)
    spc_node = parent_node.add_object(_nid(np_, opcua_idx), _qn("SPC", opcua_idx))

    vars_dict = {}
    p = machine_prefix

    # X-bar Chart sub-node
    xbar_p = f"{np_}.XBarChart"
    xbar_node = spc_node.add_object(_nid(xbar_p, opcua_idx), _qn("XBarChart", opcua_idx))
    vars_dict["xbar_current"] = _add_prefixed_var(xbar_node, opcua_idx, "XBar", 0.0, p, f"{xbar_p}.XBar")
    vars_dict["xbar_ucl"] = _add_prefixed_var(xbar_node, opcua_idx, "UCL", 0.0, p, f"{xbar_p}.UCL")
    vars_dict["xbar_cl"] = _add_prefixed_var(xbar_node, opcua_idx, "CL", 0.0, p, f"{xbar_p}.CL")
    vars_dict["xbar_lcl"] = _add_prefixed_var(xbar_node, opcua_idx, "LCL", 0.0, p, f"{xbar_p}.LCL")

    # R Chart sub-node
    r_p = f"{np_}.RChart"
    r_node = spc_node.add_object(_nid(r_p, opcua_idx), _qn("RChart", opcua_idx))
    vars_dict["r_current"] = _add_prefixed_var(r_node, opcua_idx, "Range", 0.0, p, f"{r_p}.Range")
    vars_dict["r_ucl"] = _add_prefixed_var(r_node, opcua_idx, "UCL", 0.0, p, f"{r_p}.UCL")
    vars_dict["r_cl"] = _add_prefixed_var(r_node, opcua_idx, "CL", 0.0, p, f"{r_p}.CL")
    vars_dict["r_lcl"] = _add_prefixed_var(r_node, opcua_idx, "LCL", 0.0, p, f"{r_p}.LCL")

    # Capability sub-node
    cap_p = f"{np_}.Capability"
    cap_node = spc_node.add_object(_nid(cap_p, opcua_idx), _qn("Capability", opcua_idx))
    vars_dict["cp"] = _add_prefixed_var(cap_node, opcua_idx, "Cp", 0.0, p, f"{cap_p}.Cp")
    vars_dict["cpk"] = _add_prefixed_var(cap_node, opcua_idx, "Cpk", 0.0, p, f"{cap_p}.Cpk")
    vars_dict["pp"] = _add_prefixed_var(cap_node, opcua_idx, "Pp", 0.0, p, f"{cap_p}.Pp")
    vars_dict["ppk"] = _add_prefixed_var(cap_node, opcua_idx, "Ppk", 0.0, p, f"{cap_p}.Ppk")
    vars_dict["sigma_level"] = _add_prefixed_var(cap_node, opcua_idx, "SigmaLevel", 0.0, p, f"{cap_p}.SigmaLevel")

    # Status sub-node
    stat_p = f"{np_}.Status"
    status_node = spc_node.add_object(_nid(stat_p, opcua_idx), _qn("Status", opcua_idx))
    vars_dict["in_control"] = _add_prefixed_var(status_node, opcua_idx, "InControl", True, p, f"{stat_p}.InControl")
    vars_dict["violations"] = _add_prefixed_var(status_node, opcua_idx, "Violations", "", p, f"{stat_p}.Violations")
    vars_dict["total_samples"] = _add_prefixed_var(status_node, opcua_idx, "TotalSamples", 0, p, f"{stat_p}.TotalSamples")
    vars_dict["num_subgroups"] = _add_prefixed_var(status_node, opcua_idx, "NumSubgroups", 0, p, f"{stat_p}.NumSubgroups")

    return vars_dict


def create_shift_management_node(parent_node, opcua_idx: int, node_prefix: str = ""):
    """
    Create ShiftManagement sub-node under SupportFunctions (ISA-95 aligned).

    Args:
        parent_node: Parent OPC UA node (SupportFunctions object)
        opcua_idx: OPC UA namespace index
        node_prefix: Dot-separated prefix for explicit NodeIds

    Returns:
        dict: Dictionary of shift variable objects
    """
    p = node_prefix
    shift_node = parent_node.add_object(_nid(p, opcua_idx), _qn("ShiftManagement", opcua_idx))

    vars_dict = {}

    # Current shift information
    vars_dict["shift_number"] = shift_node.add_variable(_nid(f"{p}.CurrentShiftNumber", opcua_idx), _qn("CurrentShiftNumber", opcua_idx), 1)
    vars_dict["shift_name"] = shift_node.add_variable(_nid(f"{p}.CurrentShiftName", opcua_idx), _qn("CurrentShiftName", opcua_idx), "")
    vars_dict["shift_start_time"] = shift_node.add_variable(_nid(f"{p}.ShiftStartTime", opcua_idx), _qn("ShiftStartTime", opcua_idx), 0.0)
    vars_dict["shift_start_datetime"] = shift_node.add_variable(_nid(f"{p}.ShiftStartDateTime", opcua_idx), _qn("ShiftStartDateTime", opcua_idx), datetime.now())
    vars_dict["shift_end_time"] = shift_node.add_variable(_nid(f"{p}.ShiftEndTime", opcua_idx), _qn("ShiftEndTime", opcua_idx), 0.0)
    vars_dict["shift_duration"] = shift_node.add_variable(_nid(f"{p}.ShiftDuration", opcua_idx), _qn("ShiftDuration", opcua_idx), 0.0)
    vars_dict["shift_elapsed"] = shift_node.add_variable(_nid(f"{p}.ShiftElapsedTime", opcua_idx), _qn("ShiftElapsedTime", opcua_idx), 0.0)
    vars_dict["shift_remaining"] = shift_node.add_variable(_nid(f"{p}.ShiftTimeRemaining", opcua_idx), _qn("ShiftTimeRemaining", opcua_idx), 0.0)

    # Current shift metrics (reset at shift end)
    cs_p = f"{p}.CurrentShift"
    current_node = shift_node.add_object(_nid(cs_p, opcua_idx), _qn("CurrentShift", opcua_idx))
    vars_dict["current_parts"] = current_node.add_variable(_nid(f"{cs_p}.PartsProduced", opcua_idx), _qn("PartsProduced", opcua_idx), 0)
    vars_dict["current_good"] = current_node.add_variable(_nid(f"{cs_p}.GoodParts", opcua_idx), _qn("GoodParts", opcua_idx), 0)
    vars_dict["current_defects"] = current_node.add_variable(_nid(f"{cs_p}.DefectiveParts", opcua_idx), _qn("DefectiveParts", opcua_idx), 0)
    vars_dict["current_defect_rate"] = current_node.add_variable(_nid(f"{cs_p}.DefectRate", opcua_idx), _qn("DefectRate", opcua_idx), 0.0)
    vars_dict["current_availability"] = current_node.add_variable(_nid(f"{cs_p}.Availability", opcua_idx), _qn("Availability", opcua_idx), 0.0)
    vars_dict["current_performance"] = current_node.add_variable(_nid(f"{cs_p}.Performance", opcua_idx), _qn("Performance", opcua_idx), 0.0)
    vars_dict["current_quality"] = current_node.add_variable(_nid(f"{cs_p}.Quality", opcua_idx), _qn("Quality", opcua_idx), 1.0)
    vars_dict["current_oee"] = current_node.add_variable(_nid(f"{cs_p}.OEE", opcua_idx), _qn("OEE", opcua_idx), 0.0)

    # Previous shift summary (for reporting)
    ps_p = f"{p}.PreviousShift"
    prev_node = shift_node.add_object(_nid(ps_p, opcua_idx), _qn("PreviousShift", opcua_idx))
    vars_dict["prev_shift_number"] = prev_node.add_variable(_nid(f"{ps_p}.ShiftNumber", opcua_idx), _qn("ShiftNumber", opcua_idx), 0)
    vars_dict["prev_shift_name"] = prev_node.add_variable(_nid(f"{ps_p}.ShiftName", opcua_idx), _qn("ShiftName", opcua_idx), "")
    vars_dict["prev_parts"] = prev_node.add_variable(_nid(f"{ps_p}.PartsProduced", opcua_idx), _qn("PartsProduced", opcua_idx), 0)
    vars_dict["prev_good"] = prev_node.add_variable(_nid(f"{ps_p}.GoodParts", opcua_idx), _qn("GoodParts", opcua_idx), 0)
    vars_dict["prev_defects"] = prev_node.add_variable(_nid(f"{ps_p}.DefectiveParts", opcua_idx), _qn("DefectiveParts", opcua_idx), 0)
    vars_dict["prev_defect_rate"] = prev_node.add_variable(_nid(f"{ps_p}.DefectRate", opcua_idx), _qn("DefectRate", opcua_idx), 0.0)
    vars_dict["prev_oee"] = prev_node.add_variable(_nid(f"{ps_p}.OEE", opcua_idx), _qn("OEE", opcua_idx), 0.0)

    # Overall totals (never reset)
    t_p = f"{p}.Totals"
    totals_node = shift_node.add_object(_nid(t_p, opcua_idx), _qn("Totals", opcua_idx))
    vars_dict["total_parts"] = totals_node.add_variable(_nid(f"{t_p}.TotalPartsProduced", opcua_idx), _qn("TotalPartsProduced", opcua_idx), 0)
    vars_dict["total_good"] = totals_node.add_variable(_nid(f"{t_p}.TotalGoodParts", opcua_idx), _qn("TotalGoodParts", opcua_idx), 0)
    vars_dict["total_defects"] = totals_node.add_variable(_nid(f"{t_p}.TotalDefectiveParts", opcua_idx), _qn("TotalDefectiveParts", opcua_idx), 0)
    vars_dict["total_defect_rate"] = totals_node.add_variable(_nid(f"{t_p}.TotalDefectRate", opcua_idx), _qn("TotalDefectRate", opcua_idx), 0.0)
    vars_dict["total_shifts"] = totals_node.add_variable(_nid(f"{t_p}.TotalShiftsCompleted", opcua_idx), _qn("TotalShiftsCompleted", opcua_idx), 0)

    return vars_dict


def detect_machine_state(machine, health_state: int = 0, maint_active: bool = False) -> str:
    """
    Determine machine state based on Simantha flags and health.

    Supports multi-state degradation: failed_health is read from the machine
    object (defaults to 1 for 2-state). States between 0 and failed_health
    are reported as DEGRADED.

    Args:
        machine: Simantha Machine object
        health_state: 0=healthy, >=failed_health=failed
        maint_active: True if maintainer is currently repairing this machine

    Returns:
        State string: IDLE, PROCESSING, BLOCKED, STARVED, DEGRADED,
                      FAILED, UNDER_REPAIR
    """
    failed_health = getattr(machine, "failed_health", 1)

    if health_state >= failed_health:
        return "UNDER_REPAIR" if maint_active else "FAILED"

    if machine.blocked:
        return "BLOCKED"
    elif machine.starved:
        return "STARVED"
    elif health_state > 0:
        return "DEGRADED"
    elif machine.has_part:
        return "PROCESSING"
    else:
        return "IDLE"


def analyze_part_routing(sink):
    """
    Analyze routing history of parts collected by a sink.

    Args:
        sink: Simantha Sink object (with optional .contents attribute)

    Returns:
        dict with keys:
            total_parts: Number of parts in the sink
            unique_routes: Number of distinct routes taken
            route_counts: dict mapping route string to count
    """
    result = {"total_parts": 0, "unique_routes": 0, "route_counts": {}}

    if not hasattr(sink, "contents"):
        return result

    parts = sink.contents
    result["total_parts"] = len(parts)

    routes = Counter()
    for part in parts:
        if hasattr(part, "routing_history"):
            route_str = " -> ".join(part.routing_history)
        else:
            route_str = "unknown"
        routes[route_str] += 1

    result["route_counts"] = dict(routes)
    result["unique_routes"] = len(routes)
    return result


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
        "DEGRADED": "processing_time",
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
        good_parts: Parts without defects (optional)
        defective_parts: Parts with defects (optional)

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

    # Quality = GoodParts / TotalParts
    if good_parts is None:
        # Fallback behavior when no defect data provided
        good_parts = partcount
        defective_parts = 0
        quality = 1.0 if partcount > 0 else 0.0
    else:
        # Use actual defect data
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


def calculate_oee_from_sim(sim_time, machine_downtime, parts_made, cycle_time,
                           good_parts=None, defective_parts=None):
    """Calculate OEE from Simantha's authoritative per-run data."""
    if sim_time <= 0:
        return {"availability": 0, "performance": 0, "quality": 0, "oee": 0,
                "good_parts": 0, "defective_parts": 0, "theoretical_output": 0}

    # Availability = (RunTime - Downtime) / RunTime
    availability = max(0.0, min(1.0, (sim_time - machine_downtime) / sim_time))

    # Performance = ActualOutput / TheoreticalOutput
    available_time = sim_time - machine_downtime
    if available_time > 0 and cycle_time > 0:
        theoretical_output = available_time / cycle_time
        performance = max(0.0, min(1.0, parts_made / theoretical_output))
    else:
        theoretical_output = 0.0
        performance = 0.0

    # Quality
    total_parts = parts_made
    if good_parts is not None and total_parts > 0:
        quality = max(0.0, min(1.0, good_parts / total_parts))
    else:
        good_parts = parts_made
        defective_parts = 0
        quality = 1.0 if parts_made > 0 else 0.0

    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": availability * performance * quality,
        "good_parts": good_parts,
        "defective_parts": defective_parts or 0,
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
    Mark a part as defective with traceability information.

    Args:
        part: Simantha Part object
        machine_name: Name of machine that produced the defect
        defect_type: Type of defect (default: "quality")
    """
    part.is_defective = True
    part.failed_at_machine = machine_name
    part.defect_type = defect_type


def analyze_part_quality(sink, machines=None, scrap_sinks=None) -> dict:
    """
    Analyze quality of all parts produced (finished + scrapped).

    When quality routing is active, defective parts are diverted to scrap
    sinks and never reach the main sink. This function uses machine-level
    counters (_scrap_count, _good_count) as the authoritative source.

    Args:
        sink: Simantha Sink object (finished goods)
        machines: dict of machine_name -> machine_obj (for quality counters)
        scrap_sinks: dict of scrap_name -> Sink obj (for scrapped part counts)

    Returns:
        dict: Quality analysis metrics
    """
    finished_parts = sink.level

    # Count scrapped parts from scrap sinks
    scrapped_parts = 0
    if scrap_sinks:
        for scrap_obj in scrap_sinks.values():
            scrapped_parts += scrap_obj.level

    # Collect per-machine quality stats from routing counters
    defect_by_machine = {}
    rework_by_machine = {}
    total_scrap = 0
    total_rework = 0
    total_rework_success = 0
    if machines:
        for name, m in machines.items():
            if hasattr(m, '_scrap_count'):
                scrap = m._scrap_count
                defective = m._defective_count
                machine_defects = scrap + defective
                if machine_defects > 0:
                    defect_by_machine[name] = machine_defects
                total_scrap += scrap
                total_rework += m._rework_count
                total_rework_success += m._rework_success_count
                if m._rework_count > 0:
                    rework_by_machine[name] = {
                        "attempts": m._rework_count,
                        "successes": m._rework_success_count,
                    }

    # Total parts = finished goods + scrapped (reworked successes already in finished)
    total_parts = finished_parts + scrapped_parts
    defective_count = scrapped_parts  # scrapped = confirmed defective
    good_parts = finished_parts
    first_pass_yield = good_parts / total_parts if total_parts > 0 else 0.0

    return {
        "total_parts": total_parts,
        "good_parts": good_parts,
        "defective_parts": defective_count,
        "first_pass_yield": first_pass_yield,
        "defect_by_machine": defect_by_machine,
        "rework_by_machine": rework_by_machine,
        "total_rework_attempts": total_rework,
        "total_rework_successes": total_rework_success,
    }


# ========== MAIN LOOP STEP FUNCTIONS ==========


def read_opcua_controls(opcua_vars):
    """Read the configured interarrival time from the OPC UA node.

    SetInterarrivalTime is read-only during a run — it reflects the value
    the simulation was started with.  Reading it here keeps source.interarrival_time
    in sync if the value was set via the start API rather than YAML directly.
    """
    return float(opcua_vars["system"]["interarrival_time"].get_value())


def update_part_counter(sink_level, prev_sink_level):
    """Read throughput directly from sink.level.

    Each system.simulate() call reinitializes the entire simulation and runs
    from time 0, so sink.level is the authoritative total for the current run
    length. delta_parts is the change since the previous step.

    Returns:
        tuple: (delta_parts, total_parts_produced, prev_sink_level)
    """
    delta_parts = max(0, sink_level - prev_sink_level)
    total_parts_produced = sink_level
    return delta_parts, total_parts_produced, sink_level


def check_shift_rotation(shift_manager, sim_time):
    """Check and perform shift rotation if needed. Returns whether shift rotated."""
    if shift_manager:
        shift_rotated = shift_manager.check_shift_rotation(sim_time)
        if shift_rotated:
            print(f"\n[SHIFT CHANGE] Shift {shift_manager.current_shift_number} started: "
                  f"{shift_manager.shift_definitions[shift_manager.current_shift_index].name}")
        return shift_rotated
    return False


def collect_system_metrics(buffers, maintainer, machines=None):
    """Collect system-level metrics: WIP, maintenance status.

    Args:
        buffers: Dict of buffer objects
        maintainer: Simantha Maintainer object (or None)
        machines: Dict of machine objects (for repair count aggregation)

    Returns:
        tuple: (total_wip, maint_active, maint_queue_length, total_repairs)
    """
    total_wip = sum(buffer.level for buffer in buffers.values())

    if maintainer is not None:
        try:
            maint_active = maintainer.utilization > 0
        except AttributeError:
            maint_active = False
        try:
            maint_queue_length = len(maintainer.get_queue())
        except (AttributeError, TypeError):
            maint_queue_length = 0
        # Aggregate repair counts from machines (AdvancedMachine tracks cm/pm counts)
        total_repairs = 0
        if machines:
            for m in machines.values():
                total_repairs += getattr(m, 'total_cm_count', 0) + getattr(m, 'total_pm_count', 0)
    else:
        maint_active = False
        maint_queue_length = 0
        total_repairs = 0

    return total_wip, maint_active, maint_queue_length, total_repairs


def process_machine_step(machine_name, machine_obj, metrics, config_machines,
                         total_parts_produced, sim_step, maintainer,
                         shift_manager, spc_monitors, opcua_vars, sink, sim_time,
                         shift_oee_snapshot=None, shift_start_time=0.0,
                         machine_totals=None):
    """Process one simulation step for a single machine.

    Updates metrics, detects state, calculates OEE, updates alarms, SPC,
    and writes all OPC UA variables for this machine.

    Args:
        shift_oee_snapshot: Dict with shift-start counters for shift-relative OEE.
        shift_start_time: sim_time when current shift started.

    Returns:
        list or None: Alarms triggered this step (for historian), or None.
    """
    # Store previous partcount for defect calculation
    prev_partcount = metrics["partcount"]

    # Accumulate time based on previous state
    accumulate_time(metrics, metrics["prev_state"], sim_step)

    # Detect current state
    machine_cfg = next(m for m in config_machines if m["name"] == machine_name)
    enable_health = (machine_cfg.get("enable_degradation", False)
                     or machine_cfg.get("enable_advanced_failures", False))
    health_state = machine_obj.health if enable_health else 0

    # Check if this machine is being repaired (use machine attribute, not maintainer)
    machine_maint_active = getattr(machine_obj, 'under_repair', False)

    current_state = detect_machine_state(machine_obj, health_state, machine_maint_active)
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
    if shift_manager:
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

    # OEE calculation — every step, using shift-relative deltas.
    # Uses metrics["down_time"] (our accumulator, excludes warm-up) instead of
    # machine_obj.downtime (Simantha's counter, includes warm-up).
    snap = shift_oee_snapshot or {}
    shift_elapsed = sim_time - shift_start_time
    shift_downtime = metrics["down_time"] - snap.get("down_time_accum", 0.0)

    # Read authoritative counters from LineState (machine_totals) when available.
    # Falls back to Simantha object attributes for call sites that don't yet
    # provide machine_totals (e.g. tests calling process_machine_step directly).
    _parts_made = machine_totals.parts_made if machine_totals else machine_obj.parts_made
    shift_parts = _parts_made - snap.get("parts_made", 0)

    if isinstance(machine_obj, QualityRoutingMixin):
        if machine_totals:
            _good = machine_totals.good_count
            _scrap = machine_totals.scrap_count
            _defective = machine_totals.defective_count
        else:
            _good = machine_obj._good_count
            _scrap = machine_obj._scrap_count
            _defective = getattr(machine_obj, '_defective_count', 0)
        qr_good = _good - snap.get("good_count", 0)
        qr_defective = (_scrap + _defective) - snap.get("scrap_count", 0) - snap.get("defective_count", 0)
    else:
        qr_good = metrics["good_parts"] - snap.get("metric_good", 0)
        qr_defective = metrics["defective_parts"] - snap.get("metric_defective", 0)

    oee_result = calculate_oee_from_sim(
        shift_elapsed, shift_downtime, shift_parts,
        metrics["cycle_time"],
        good_parts=max(0, qr_good), defective_parts=max(0, qr_defective)
    )
    metrics["oee_cached"] = oee_result

    metrics["oee"] = oee_result["oee"]

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

    # PPM (parts per minute)
    machine_vars["target_ppm"].set_value(metrics.get("target_ppm", 0.0))
    total_time = (metrics["processing_time"] + metrics["blocked_time"]
                  + metrics["starved_time"] + metrics["down_time"]
                  + metrics["idle_time"])
    total_time_min = total_time / 60.0
    actual_ppm = metrics["partcount"] / total_time_min if total_time_min > 0 else 0.0
    machine_vars["actual_ppm"].set_value(round(actual_ppm, 2))
    # Health (if enabled)
    if "health" in machine_vars:
        failed_health = getattr(machine_obj, "failed_health", 1)
        health_pct = 100.0 * (1 - health_state / failed_health) if failed_health > 0 else 0.0
        machine_vars["health"].set_value(health_state)
        machine_vars["health_pct"].set_value(round(health_pct, 1))

    # Failure mode statistics
    if isinstance(machine_obj, AdvancedMachine) and "fm_active" in machine_vars:
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
                # Simulate real measurement with natural process variation
                noise_cv = metrics.get("spc_measurement_noise", 0.02)
                measurement = metrics["cycle_time"] * (1.0 + random.gauss(0, noise_cv))
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
    """Calculate line-level OEE using bottleneck model (minimum of all machines).

    Returns:
        tuple: (line_availability, line_performance, line_quality, line_oee)
    """
    all_oee_results = []
    for m in machines.keys():
        cached = machine_metrics[m].get("oee_cached")
        if cached:
            all_oee_results.append(cached)
        else:
            all_oee_results.append({"availability": 0, "performance": 0, "quality": 0, "oee": 0})

    line_availability = min(r["availability"] for r in all_oee_results) if all_oee_results else 0.0
    line_performance = min(r["performance"] for r in all_oee_results) if all_oee_results else 0.0
    line_quality = min(r["quality"] for r in all_oee_results) if all_oee_results else 0.0
    line_oee = line_availability * line_performance * line_quality

    return line_availability, line_performance, line_quality, line_oee


def write_system_opcua_vars(opcua_vars, sim_time, total_parts_produced, total_wip,
                            line_availability, line_performance, line_quality, line_oee,
                            maint_active, maint_queue_length, total_repairs,
                            line_good_parts=0, line_defective_parts=0):
    """Write system-level and line-level KPIs to OPC UA."""
    opcua_vars["system"]["simtime"].set_value(sim_time)
    opcua_vars["system"]["throughput"].set_value(total_parts_produced)

    # ISA-95 LineState
    line_state = "RUNNING" if total_parts_produced > 0 or maint_active else "STOPPED"
    opcua_vars["system"]["line_state"].set_value(line_state)

    opcua_vars["line_kpis"]["total_wip"].set_value(total_wip)
    opcua_vars["line_kpis"]["line_availability"].set_value(line_availability)
    opcua_vars["line_kpis"]["line_performance"].set_value(line_performance)
    opcua_vars["line_kpis"]["line_quality"].set_value(line_quality)
    opcua_vars["line_kpis"]["line_oee"].set_value(line_oee)
    if "line_good_parts" in opcua_vars["line_kpis"]:
        opcua_vars["line_kpis"]["line_good_parts"].set_value(line_good_parts)
        opcua_vars["line_kpis"]["line_defective_parts"].set_value(line_defective_parts)

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
    if "shift_start_datetime" in sv:
        sv["shift_start_datetime"].set_value(
            shift_info.get("shift_start_wall_clock", datetime.now())
        )
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
                            production_summary_counter, production_summary_interval, sim_step,
                            line_availability=0.0, line_performance=0.0, line_quality=0.0):
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
                line_availability=line_availability,
                line_performance=line_performance,
                line_quality=line_quality,
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
               scrap_sinks: {"ScrapBin1": sink_obj, ...} (empty if none)
    """
    source = Source()
    sink = Sink(collect_parts=True)

    # Create scrap sinks
    scrap_sinks = {}
    for scrap_cfg in config.get("scrap_sinks", []):
        scrap_sinks[scrap_cfg["name"]] = Sink(
            name=scrap_cfg["name"], collect_parts=True
        )

    # Create machines from config
    machines = {}
    for machine_cfg in config["machines"]:
        name = machine_cfg["name"]
        # Derive cycle_time from target_ppm if provided, otherwise use direct value
        if "target_ppm" in machine_cfg:
            target_ppm = machine_cfg["target_ppm"]
            cycle_time = max(1, int(60.0 / target_ppm))
        else:
            cycle_time = int(machine_cfg.get("cycle_time", 1))  # Convert to int for Simantha
        enable_advanced_failures = machine_cfg.get("enable_advanced_failures", False)
        enable_degradation = machine_cfg.get("enable_degradation", False)

        # Check for quality routing
        quality_cfg = machine_cfg.get("quality_routing", {})
        has_quality_routing = quality_cfg.get("enabled", False)

        # Build degradation kwargs (shared across machine types)
        degradation_kwargs = {}
        if enable_degradation:
            health_cfg = machine_cfg.get("health_states", {})
            if health_cfg:
                from simantha.utils import generate_degradation_matrix
                h_max = health_cfg.get("h_max", 1)
                p_degrade = health_cfg.get("p_degrade", 0.01)
                degradation_kwargs["degradation_matrix"] = generate_degradation_matrix(
                    p=p_degrade, h_max=h_max
                )
                degradation_kwargs["cbm_threshold"] = health_cfg.get("cbm_threshold", 1)
            else:
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

    # Wire scrap sinks to machines (after all objects created)
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
        strategy = maintainer_cfg.get("strategy", "fifo")
        capacity = maintainer_cfg.get("capacity", 1)
        if strategy != "fifo":
            from priority_maintainer import PriorityMaintainer
            machine_priorities = maintainer_cfg.get("machine_priorities", {})
            maintainer = PriorityMaintainer(
                capacity=capacity, strategy=strategy,
                machine_priorities=machine_priorities
            )
        else:
            maintainer = Maintainer(capacity=capacity)
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
    Build ISA-95/ISO 23247 aligned OPC UA server from config.

    Creates an address space with the ISA-95 hierarchy:
      Enterprise / Site / Area / Line_Equipment + Line_Asset

    Under Line_Equipment:
      Identification, OperationsState, OperationsPerformance, OEE,
      Resources (machines, buffers, scrap), SupportFunctions (maintenance, shifts)

    Args:
        config: Dict with keys 'machines', 'buffers', 'maintainer', and optional
                'enterprise', 'site', 'area', 'line_name' for ISA-95 naming.

    Returns:
        tuple: (server, opcua_vars, idx)
               opcua_vars is a structured dict:
               {
                   "system": {simtime, throughput, pause_line, interarrival_time, ...},
                   "line_kpis": {total_wip, line_availability, ...},
                   "machines": {"M1": {...}, "M2": {...}, ...},
                   "buffers": {"B1": {...}, "B2": {...}, ...},
                   "maintenance": {active, queue, total_repairs},
                   "shift": {...},
                   "scrap_sinks": {...},
                   "scrap_kpis": {...},
               }
    """
    server = Server()
    server.set_server_name("Simantha Digital Twin OPC UA Server")
    server.set_endpoint("opc.tcp://0.0.0.0:4840/simantha/")

    # Override default FreeOpcUa identity so industrial clients show a
    # meaningful name instead of "Generic OPC UA server / urn:freeopcua:..."
    server.set_application_uri("urn:simantha:nist:digitaltwin:server")
    server.product_uri = "https://github.com/usnistgov/simantha"
    server.manufacturer_name = "NIST / Simantha"
    server.set_build_info(
        server.product_uri,
        server.manufacturer_name,
        "Simantha Digital Twin OPC UA Server",
        "2.1.0",
        "1",
        datetime.now(),
    )

    # Set ServerProfileArray so clients know our capability level
    profile_node = server.get_node(ua.NodeId(ua.ObjectIds.Server_ServerCapabilities_ServerProfileArray))
    profile_node.set_value([
        "http://opcfoundation.org/UA-Profile/Server/NanoEmbeddedDevice2017",
    ])

    uri = "http://simantha.nist.gov/"
    idx = server.register_namespace(uri)

    objects = server.get_objects_node()

    # --- ISA-95 hierarchy: Enterprise > Site > Area ---
    ent_name = config.get("enterprise", "WeylandIndustries")
    site_name = config.get("site", "LV426_Colony")
    area_name = config.get("area", "AtmosphereProcessor01")
    line_name = config.get("line_name", "Nostromo_BioProductPakaging")

    enterprise = objects.add_object(_nid(ent_name, idx), _qn(ent_name, idx))
    site = enterprise.add_object(_nid(f"{ent_name}.{site_name}", idx), _qn(site_name, idx))
    area = site.add_object(_nid(f"{ent_name}.{site_name}.{area_name}", idx), _qn(area_name, idx))

    # Line Equipment and Line Asset nodes
    equip_name = f"{line_name}_Equipment"
    asset_name = f"{line_name}_Asset"
    ep = f"{ent_name}.{site_name}.{area_name}.{equip_name}"  # equipment prefix
    ap = f"{ent_name}.{site_name}.{area_name}.{asset_name}"  # asset prefix

    line_equip = area.add_object(_nid(ep, idx), _qn(equip_name, idx))
    line_asset = area.add_object(_nid(ap, idx), _qn(asset_name, idx))

    # --- Line Asset identification (static metadata) ---
    la_id_p = f"{ap}.Identification"
    la_id_node = line_asset.add_object(_nid(la_id_p, idx), _qn("Identification", idx))
    la_id_node.add_variable(_nid(f"{la_id_p}.PhysicalAssetID", idx), _qn("PhysicalAssetID", idx), asset_name)
    la_id_node.add_variable(_nid(f"{la_id_p}.AssetClass", idx), _qn("AssetClass", idx), "ProductionLine")
    la_id_node.add_variable(_nid(f"{la_id_p}.Description", idx), _qn("Description", idx), f"Physical asset for {line_name}")

    # --- Line Equipment > Identification ---
    le_id_p = f"{ep}.Identification"
    le_id_node = line_equip.add_object(_nid(le_id_p, idx), _qn("Identification", idx))
    le_id_node.add_variable(_nid(f"{le_id_p}.EquipmentID", idx), _qn("EquipmentID", idx), "Line1")
    le_id_node.add_variable(_nid(f"{le_id_p}.EquipmentClass", idx), _qn("EquipmentClass", idx), "ProductionLine")
    le_id_node.add_variable(_nid(f"{le_id_p}.Description", idx), _qn("Description", idx), f"Digital twin of {line_name}")
    var_run_id = le_id_node.add_variable(_nid(f"{le_id_p}.RunID", idx), _qn("RunID", idx), "")

    # --- Line Equipment > OperationsState ---
    os_p = f"{ep}.OperationsState"
    ops_state = line_equip.add_object(_nid(os_p, idx), _qn("OperationsState", idx))
    var_simtime = ops_state.add_variable(_nid(f"{os_p}.SimTime", idx), _qn("SimTime", idx), 0.0)
    var_line_state = ops_state.add_variable(_nid(f"{os_p}.LineState", idx), _qn("LineState", idx), "STOPPED")
    var_line_mode = ops_state.add_variable(_nid(f"{os_p}.LineMode", idx), _qn("LineMode", idx), "AUTO")
    # Controls under OperationsState (read-only — set at run start, not during run)
    ctrl_p = f"{os_p}.Controls"
    controls_node = ops_state.add_object(_nid(ctrl_p, idx), _qn("Controls", idx))
    default_interarrival = config.get("source", {}).get("interarrival_time", 1.0)
    var_interarrival = controls_node.add_variable(_nid(f"{ctrl_p}.SetInterarrivalTime", idx), _qn("SetInterarrivalTime", idx), default_interarrival)

    # --- Line Equipment > OperationsPerformance ---
    op_p = f"{ep}.OperationsPerformance"
    ops_perf = line_equip.add_object(_nid(op_p, idx), _qn("OperationsPerformance", idx))
    var_throughput = ops_perf.add_variable(_nid(f"{op_p}.Throughput", idx), _qn("Throughput", idx), 0)
    var_total_wip = ops_perf.add_variable(_nid(f"{op_p}.TotalWIP", idx), _qn("TotalWIP", idx), 0)
    var_total_scrap = ops_perf.add_variable(_nid(f"{op_p}.TotalScrap", idx), _qn("TotalScrap", idx), 0)
    var_scrap_rate = ops_perf.add_variable(_nid(f"{op_p}.ScrapRate", idx), _qn("ScrapRate", idx), 0.0)

    # --- Line Equipment > OEE ---
    oee_p = f"{ep}.OEE"
    line_oee_node = line_equip.add_object(_nid(oee_p, idx), _qn("OEE", idx))
    var_line_availability = line_oee_node.add_variable(_nid(f"{oee_p}.Availability", idx), _qn("Availability", idx), 0.0)
    var_line_performance = line_oee_node.add_variable(_nid(f"{oee_p}.Performance", idx), _qn("Performance", idx), 0.0)
    var_line_quality = line_oee_node.add_variable(_nid(f"{oee_p}.Quality", idx), _qn("Quality", idx), 1.0)
    var_line_oee = line_oee_node.add_variable(_nid(f"{oee_p}.OEE", idx), _qn("OEE", idx), 0.0)
    var_line_good_parts = line_oee_node.add_variable(_nid(f"{oee_p}.GoodPartCount", idx), _qn("GoodPartCount", idx), 0)
    var_line_defective_parts = line_oee_node.add_variable(_nid(f"{oee_p}.DefectivePartCount", idx), _qn("DefectivePartCount", idx), 0)

    # --- Line Equipment > Resources ---
    res_p = f"{ep}.Resources"
    resources = line_equip.add_object(_nid(res_p, idx), _qn("Resources", idx))

    # EventLog under line equipment
    el_p = f"{ep}.EventLog"
    event_log_node = line_equip.add_object(_nid(el_p, idx), _qn("EventLog", idx))
    var_total_events = event_log_node.add_variable(_nid(f"{el_p}.TotalEventsGenerated", idx), _qn("TotalEventsGenerated", idx), 0)

    # --- Resources > Machine Equipment + Asset nodes ---
    machines_vars = {}
    for i, machine_cfg in enumerate(config["machines"], start=1):
        machine_name = machine_cfg["name"]
        equip_node_name = f"M{i}_Equipment"
        asset_node_name = f"M{i}_Asset"
        enable_health = (machine_cfg.get("enable_degradation", False)
                         or machine_cfg.get("enable_advanced_failures", False))

        enable_failure_modes = machine_cfg.get("enable_advanced_failures", False)
        failure_mode_names = []
        if enable_failure_modes:
            failure_mode_names = [fm["name"] for fm in machine_cfg.get("failure_modes", [])]

        enable_spc = machine_cfg.get("enable_spc", False)
        enable_quality_routing = machine_cfg.get("quality_routing", {}).get("enabled", False)

        machine_vars = create_machine_node(resources, idx, equip_node_name, enable_health,
                                           enable_failure_modes, failure_mode_names,
                                           enable_spc, enable_quality_routing,
                                           node_prefix=f"{res_p}.{equip_node_name}")
        machines_vars[machine_name] = machine_vars

        # Physical asset node
        create_machine_asset_node(resources, idx, asset_node_name,
                                  node_prefix=f"{res_p}.{asset_node_name}")

    # --- Resources > Buffer StorageUnit nodes ---
    buffers_vars = {}
    for i, buffer_cfg in enumerate(config["buffers"], start=1):
        buffer_name = buffer_cfg["name"]
        unit_name = f"B{i}_StorageUnit"
        capacity = buffer_cfg.get("capacity", 10)

        buffer_vars = create_storage_unit_node(resources, idx, unit_name, capacity,
                                               node_prefix=f"{res_p}.{unit_name}",
                                               include_alarms=True)
        buffers_vars[buffer_name] = buffer_vars

    # --- Resources > Scrap StorageUnit nodes ---
    scrap_vars = {}
    for scrap_cfg in config.get("scrap_sinks", []):
        scrap_name = scrap_cfg["name"]
        unit_name = f"{scrap_name}_StorageUnit"
        scrap_unit_vars = create_storage_unit_node(resources, idx, unit_name, -1,
                                                   node_prefix=f"{res_p}.{unit_name}",
                                                   include_alarms=False)
        scrap_vars[scrap_name] = scrap_unit_vars

    # --- SupportFunctions ---
    sf_p = f"{ep}.SupportFunctions"
    support = line_equip.add_object(_nid(sf_p, idx), _qn("SupportFunctions", idx))

    # Maintenance
    maint_p = f"{sf_p}.Maintenance"
    maintenance_node = support.add_object(_nid(maint_p, idx), _qn("Maintenance", idx))
    var_maint_active = maintenance_node.add_variable(_nid(f"{maint_p}.MaintenanceActive", idx), _qn("MaintenanceActive", idx), False)
    var_maint_queue = maintenance_node.add_variable(_nid(f"{maint_p}.QueueLength", idx), _qn("QueueLength", idx), 0)
    var_total_repairs = maintenance_node.add_variable(_nid(f"{maint_p}.TotalRepairs", idx), _qn("TotalRepairs", idx), 0)

    # Shift tracking (optional)
    shift_vars = {}
    if "shifts" in config:
        shift_vars = create_shift_management_node(support, idx,
                                                  node_prefix=f"{sf_p}.ShiftManagement")

    # --- Recipe tracking (under OperationsState) ---
    rcp_p = f"{os_p}.Recipe"
    recipe_node = ops_state.add_object(_nid(rcp_p, idx), _qn("Recipe", idx))
    var_recipe_name = recipe_node.add_variable(_nid(f"{rcp_p}.RecipeName", idx), _qn("RecipeName", idx), "")
    var_recipe_desc = recipe_node.add_variable(_nid(f"{rcp_p}.RecipeDescription", idx), _qn("RecipeDescription", idx), "")
    var_seg_name = recipe_node.add_variable(_nid(f"{rcp_p}.SegmentName", idx), _qn("SegmentName", idx), "")
    var_seg_index = recipe_node.add_variable(_nid(f"{rcp_p}.SegmentIndex", idx), _qn("SegmentIndex", idx), 0)
    var_total_segments = recipe_node.add_variable(_nid(f"{rcp_p}.TotalSegments", idx), _qn("TotalSegments", idx), 0)
    var_seg_time_remaining = recipe_node.add_variable(_nid(f"{rcp_p}.SegmentTimeRemaining", idx), _qn("SegmentTimeRemaining", idx), 0.0)
    var_seg_qty_target = recipe_node.add_variable(_nid(f"{rcp_p}.SegmentQuantityTarget", idx), _qn("SegmentQuantityTarget", idx), 0)
    var_seg_qty_produced = recipe_node.add_variable(_nid(f"{rcp_p}.SegmentQuantityProduced", idx), _qn("SegmentQuantityProduced", idx), 0)
    var_seg_stop_mode = recipe_node.add_variable(_nid(f"{rcp_p}.SegmentStopMode", idx), _qn("SegmentStopMode", idx), "")
    var_co_state = recipe_node.add_variable(_nid(f"{rcp_p}.ChangeoverState", idx), _qn("ChangeoverState", idx), False)
    var_co_planned = recipe_node.add_variable(_nid(f"{rcp_p}.LastChangeoverPlanned", idx), _qn("LastChangeoverPlanned", idx), 0.0)
    var_co_actual = recipe_node.add_variable(_nid(f"{rcp_p}.LastChangeoverActual", idx), _qn("LastChangeoverActual", idx), 0.0)

    # No writable variables — interarrival_time is set at run start only

    # Recipe vars sub-dict
    recipe_vars = {
        "recipe_name": var_recipe_name,
        "recipe_description": var_recipe_desc,
        "segment_name": var_seg_name,
        "segment_index": var_seg_index,
        "total_segments": var_total_segments,
        "segment_time_remaining": var_seg_time_remaining,
        "segment_quantity_target": var_seg_qty_target,
        "segment_quantity_produced": var_seg_qty_produced,
        "segment_stop_mode": var_seg_stop_mode,
        "changeover_state": var_co_state,
        "last_changeover_planned": var_co_planned,
        "last_changeover_actual": var_co_actual,
    }

    # Return structured dictionary (internal keys unchanged for main loop compatibility)
    opcua_vars = {
        "system": {
            "simtime": var_simtime,
            "throughput": var_throughput,
            "interarrival_time": var_interarrival,
            "line_state": var_line_state,
            "line_mode": var_line_mode,
            "total_events": var_total_events,
            "run_id": var_run_id,
        },
        "line_kpis": {
            "total_wip": var_total_wip,
            "line_availability": var_line_availability,
            "line_performance": var_line_performance,
            "line_quality": var_line_quality,
            "line_oee": var_line_oee,
            "line_good_parts": var_line_good_parts,
            "line_defective_parts": var_line_defective_parts,
        },
        "machines": machines_vars,
        "buffers": buffers_vars,
        "maintenance": {
            "active": var_maint_active,
            "queue": var_maint_queue,
            "total_repairs": var_total_repairs,
        },
        "shift": shift_vars,
        "scrap_sinks": scrap_vars,
        "scrap_kpis": {
            "total_scrap": var_total_scrap,
            "scrap_rate": var_scrap_rate,
        },
        "recipe": recipe_vars,
    }

    return server, opcua_vars, idx


# ========== SEGMENT RUNNER ==========


def _install_health_restorer(machine_obj, health: int) -> None:
    """Monkey-patch machine.initialize() to restore health after Simantha resets it.

    Each system.simulate() call reinitializes all objects (health → 0).  By
    wrapping initialize() we restore the saved health value immediately after
    Simantha's reset, so degradation and failures accumulate across steps.
    """
    if not hasattr(machine_obj, '_base_initialize'):
        machine_obj._base_initialize = machine_obj.initialize

    base_init = machine_obj._base_initialize
    saved_health = health

    def patched_init(env):
        base_init(env)
        machine_obj.health = saved_health

    machine_obj.initialize = patched_init


def run_segment(
    system, source, sink, machines, buffers, maintainer, scrap_sinks,
    server, opcua_vars, config, sim_seed,
    max_sim_time=float('inf'),
    target_quantity=None,
    segment_name="",
    extra_base=None,
    trace=False,
    shift_manager=None,
    historian=None,
    neo4j_hist=None,
    recipe_vars=None,
):
    """Run simulation until time limit OR quantity target is reached.

    This is the extracted core simulation loop, usable both for single-scenario
    mode (called from main with max_sim_time=inf) and for recipe segments.

    Args:
        system: Simantha System object
        source, sink: Source and Sink objects
        machines: dict of machine_name -> machine_obj
        buffers: dict of buffer_name -> buffer_obj
        maintainer: Simantha Maintainer (or None)
        scrap_sinks: dict of scrap_name -> Sink
        server: OPC UA Server
        opcua_vars: OPC UA variable dict
        config: Effective scenario config (with overrides applied)
        sim_seed: Random seed for reproducibility
        max_sim_time: Stop after this many sim-seconds (float('inf') for unlimited)
        target_quantity: Stop after this many parts produced (None for time-based)
        segment_name: For logging / OPC UA display
        extra_base: dict merged into historian events (recipe/segment context)
        trace: Enable Simantha DES event trace
        shift_manager: ShiftManager instance (shared across segments)
        historian: EventHistorian instance (shared across segments)
        neo4j_hist: Neo4jHistorian instance (shared across segments)
        recipe_vars: OPC UA recipe variables dict (or None for single-scenario)

    Returns:
        tuple: (final_sim_time, parts_produced, stop_reason, oee)
            stop_reason: "quantity_reached", "duration_reached",
                         "max_duration_reached", or "interrupted"
            oee: line-level OEE at end of segment
    """
    import numpy as np

    sim_time = 0.0
    sim_step = 1.0       # simulated seconds per loop iteration
    real_step = 1.0      # target wall-clock seconds per loop iteration
    warm_up_time = int(config.get("warm_up_time", 0))
    step_wall_start = time.time()  # initialised here; reset at top of each iteration

    # LineState owns all accumulated counters across simulate() calls.
    line_state = LineState()
    for mname in machines:
        line_state.init_machine(mname)
    total_parts_produced = 0   # kept as local convenience alias for line_state.total_parts_produced

    # Initialize per-machine metrics
    machine_metrics = {}
    spc_monitors = {}

    for machine_name in machines.keys():
        machine_cfg = next(m for m in config["machines"] if m["name"] == machine_name)
        if "target_ppm" in machine_cfg:
            target_ppm = machine_cfg["target_ppm"]
            cycle_time = max(1, int(60.0 / target_ppm))
        else:
            cycle_time = machine_cfg.get("cycle_time", 1.0)
            target_ppm = 60.0 / cycle_time

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
            "target_ppm": target_ppm,
            "good_parts": 0,
            "defective_parts": 0,
            "base_defect_rate": base_defect_rate,
            "health_multiplier": health_multiplier,
            "prev_health_state": 0,
            "prev_maint_active": False,
            "prev_defect_rate": 0.0,
            "alarm_machine_failed_active": False,
            "alarm_maintenance_active": False,
            "alarm_quality_alert_active": False,
            "oee_cached": None,
        }

        if machine_cfg.get("enable_spc", False):
            from spc_analytics import ProcessMonitor, SPCConfiguration
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
            machine_metrics[machine_name]["spc_measurement_noise"] = spc_config_dict.get("measurement_noise", 0.02)

    # Per-machine OEE shift snapshots
    shift_oee_snapshots = {}
    shift_start_time = 0.0
    for machine_name in machines:
        shift_oee_snapshots[machine_name] = {
            "down_time_accum": 0.0,
            "parts_made": 0,
            "good_count": 0,
            "scrap_count": 0,
            "defective_count": 0,
            "metric_good": 0,
            "metric_defective": 0,
        }

    historian_state = {}
    # Per-machine saved health state — carried across simulate() calls so
    # degradation accumulates.  0 = healthy at segment start.
    machine_health = {mname: 0 for mname in machines}
    production_summary_counter = 0.0
    production_summary_interval = config.get("historian", {}).get(
        "events", {}
    ).get("production_summary_interval", 60)

    stop_reason = "interrupted"
    line_oee = 0.0

    while True:
        # Pace wall-clock: sleep for whatever remains of the 1-second budget
        # after the previous iteration's work.  This keeps sim-time and
        # wall-clock tightly in sync even when the simulate step is slow.
        elapsed = time.time() - step_wall_start
        time.sleep(max(0.0, real_step - elapsed))
        step_wall_start = time.time()

        # Check stop conditions
        if sim_time >= max_sim_time:
            if target_quantity is not None:
                stop_reason = "max_duration_reached"
            else:
                stop_reason = "duration_reached"
            break
        if target_quantity is not None and total_parts_produced >= target_quantity:
            stop_reason = "quantity_reached"
            break

        # Sync source interarrival from OPC UA node (set at run start, read-only during run)
        interarrival = read_opcua_controls(opcua_vars)
        source.interarrival_time = interarrival if interarrival > 0 else None

        # Step simulation — O(1) per step regardless of run length.
        # Seed advances per step: same base seed gives the same trajectory
        # every run (reproducible), different seeds give independent runs.
        sim_time += sim_step
        step_seed = (sim_seed + line_state.step_count) % (2 ** 31)
        random.seed(step_seed)
        np.random.seed(step_seed)
        for mname, mobj in machines.items():
            mobj._counting_active = line_state.step_count >= warm_up_time
            # Restore saved health so degradation carries across steps.
            _install_health_restorer(mobj, machine_health[mname])
        system.simulate(warm_up_time=0, simulation_time=sim_step,
                        verbose=False, collect_data=False, trace=trace)
        system._last_completed_sim_time = sim_step
        system._last_warm_up_time = 0
        # Save health for next step before any post-simulate reads mutate it.
        for mname, mobj in machines.items():
            machine_health[mname] = getattr(mobj, 'health', 0)

        # Sync LineState from Simantha objects immediately after simulate().
        # Must happen before shift snapshots and process_machine_step reads.
        line_state.step_count += 1
        for mname, mobj in machines.items():
            line_state.sync_machine(mname, mobj)

        # Throughput counter — mode-aware via LineState
        delta_parts = line_state.sync_sink(sink.level)
        total_parts_produced = line_state.total_parts_produced

        # Shift rotation
        shift_rotated = check_shift_rotation(shift_manager, sim_time)
        if shift_rotated:
            shift_start_time = sim_time
            for mname in machines:
                mt = line_state.machines[mname]
                shift_oee_snapshots[mname] = {
                    "down_time_accum": machine_metrics[mname]["down_time"],
                    "parts_made": mt.parts_made,
                    "good_count": mt.good_count,
                    "scrap_count": mt.scrap_count,
                    "defective_count": mt.defective_count,
                    "metric_good": machine_metrics[mname]["good_parts"],
                    "metric_defective": machine_metrics[mname]["defective_parts"],
                }
            for mname in machines:
                machine_metrics[mname]["oee_cached"] = None

        # System metrics
        total_wip, maint_active, maint_queue_length, total_repairs = \
            collect_system_metrics(buffers, maintainer, machines)

        # Per-machine processing
        machine_alarms_map = {}
        for machine_name, machine_obj in machines.items():
            alarms = process_machine_step(
                machine_name, machine_obj, machine_metrics[machine_name],
                config["machines"], total_parts_produced, sim_step,
                maintainer, shift_manager, spc_monitors, opcua_vars, sink,
                sim_time,
                shift_oee_snapshot=shift_oee_snapshots.get(machine_name),
                shift_start_time=shift_start_time,
                machine_totals=line_state.machines.get(machine_name))
            if alarms:
                machine_alarms_map[machine_name] = alarms

        # Buffer levels and alarms
        buffer_alarms_map = update_buffers(buffers, opcua_vars)

        # Scrap tracking
        update_scrap_tracking(scrap_sinks, total_parts_produced, opcua_vars)

        # Line-level OEE
        line_avail, line_perf, line_qual, line_oee = \
            calculate_line_level_oee(machines, machine_metrics)

        line_good = sum(m.get("good_parts", 0) for m in machine_metrics.values())
        line_defective = sum(m.get("defective_parts", 0) for m in machine_metrics.values())

        # Write system KPIs to OPC UA
        write_system_opcua_vars(opcua_vars, sim_time, total_parts_produced, total_wip,
                                line_avail, line_perf, line_qual, line_oee,
                                maint_active, maint_queue_length, total_repairs,
                                line_good_parts=line_good,
                                line_defective_parts=line_defective)

        # Shift OPC UA updates
        update_shift_opcua_vars(shift_manager, opcua_vars, sim_time, delta_parts)

        # Update recipe OPC UA vars
        if recipe_vars:
            recipe_vars["segment_quantity_produced"].set_value(total_parts_produced)
            if target_quantity is None:
                recipe_vars["segment_time_remaining"].set_value(
                    max(0.0, max_sim_time - sim_time)
                )

        # Historian events
        production_summary_counter = record_historian_events(
            historian, neo4j_hist, sim_time, machines, machine_metrics,
            buffers, machine_alarms_map, buffer_alarms_map, shift_manager,
            shift_rotated, spc_monitors, historian_state, config,
            total_parts_produced, total_wip, line_oee, delta_parts,
            production_summary_counter, production_summary_interval, sim_step,
            line_availability=line_avail, line_performance=line_perf,
            line_quality=line_qual)

    return sim_time, total_parts_produced, stop_reason, line_oee


def main(argv=None):
    import argparse
    import random

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Simantha OPC UA Server")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--scenario", default=None,
                            help="Scenario name from line_models.yaml (default: balanced_line)")
    mode_group.add_argument("--recipe", default=None,
                            help="Recipe YAML name from config/recipes/ (e.g. monday_schedule)")
    parser.add_argument("--seed", type=int, default=None,
                       help="Random seed for reproducible simulation")
    parser.add_argument("--trace", action="store_true",
                       help="Enable Simantha DES event trace (outputs pickle file)")
    args = parser.parse_args(argv)

    # Default to balanced_line if neither --scenario nor --recipe given
    if args.scenario is None and args.recipe is None:
        args.scenario = "balanced_line"

    # Set random seed (seeds both Python random and numpy for scipy)
    # Auto-generate if not provided; re-used before each simulate() for monotonic results
    import numpy as np
    if args.seed is not None:
        sim_seed = args.seed
    else:
        sim_seed = int(datetime.now().timestamp() * 1000) % (2**31)
    random.seed(sim_seed)
    np.random.seed(sim_seed)
    print(f"Using random seed: {sim_seed}")

    # ---- Recipe mode ----
    if args.recipe:
        from recipe_runner import (
            load_recipe_config, parse_recipe, validate_recipe, run_recipe,
        )
        raw = load_recipe_config(args.recipe)
        recipe = parse_recipe(raw)
        validate_recipe(recipe)

        run_id = os.environ.get(
            "SIMANTHA_RUN_ID",
            f"{args.recipe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        print(f"RunID: {run_id}")

        run_recipe(recipe, sim_seed, args, run_id)
        return

    # ---- Single-scenario mode (default) ----
    # Generate RunID (env var override for web UI coordination)
    run_id = os.environ.get(
        "SIMANTHA_RUN_ID",
        f"{args.scenario}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    # Load configuration
    config = load_line_config(args.scenario)
    print(f"Loading scenario: {args.scenario}")
    print(f"RunID: {run_id}")

    # Build Simantha system from config
    system, source, sink, machines, buffers, maintainer, scrap_sinks = build_simantha_system(config)

    # Build OPC UA server from config
    server, opcua_vars, idx = build_opcua_server(config)
    opcua_vars["system"]["run_id"].set_value(run_id)

    # Create shift manager if configured
    shift_manager = create_shift_manager_from_config(config, list(machines.keys()))
    if shift_manager:
        print(f"  Shift tracking enabled: {len(shift_manager.shift_definitions)} shifts")
        for i, shift_def in enumerate(shift_manager.shift_definitions):
            print(f"    Shift {i+1}: {shift_def.name} ({shift_def.duration} time units)")

    # Create event historian if configured
    historian = create_historian_from_config(config, args.scenario, run_id=run_id)
    if historian:
        print(f"  Event historian enabled: {historian.describe()}")

    # Create Neo4j historian if configured
    neo4j_hist = create_neo4j_historian_from_config(config, args.scenario,
                                                     run_id=run_id)
    if neo4j_hist:
        neo4j_hist.create_topology(config)
        print(f"  Neo4j historian enabled: {neo4j_hist.describe()}")

    server.start()
    print(f"OPC UA server started at opc.tcp://localhost:4840/simantha/")
    print(f"Scenario: {args.scenario} ({len(machines)} machines, {len(buffers)} buffers)")
    print("Press Ctrl+C to stop.")

    try:
        run_segment(
            system=system,
            source=source,
            sink=sink,
            machines=machines,
            buffers=buffers,
            maintainer=maintainer,
            scrap_sinks=scrap_sinks,
            server=server,
            opcua_vars=opcua_vars,
            config=config,
            sim_seed=sim_seed,
            trace=args.trace,
            shift_manager=shift_manager,
            historian=historian,
            neo4j_hist=neo4j_hist,
        )

    except KeyboardInterrupt:
        print("\n\nSimulation stopped by user")

        # Restore Simantha state before analysis.
        # KeyboardInterrupt during system.simulate() leaves sink.level,
        # machine counters, and scrap sinks in a partial state because
        # simulate() reinitializes everything and re-runs from time 0.
        # Re-running the last completed sim_time restores correct values.
        import numpy as np
        last_sim = getattr(system, '_last_completed_sim_time', 0.0)
        last_wu = getattr(system, '_last_warm_up_time', 0)
        if last_sim > 0:
            try:
                random.seed(sim_seed)
                np.random.seed(sim_seed)
                system.simulate(warm_up_time=last_wu,
                                simulation_time=last_sim,
                                verbose=False, collect_data=False, trace=False)
            except Exception:
                pass  # Best effort; analysis will use whatever state exists

        # Print part quality analysis
        quality_analysis = analyze_part_quality(sink, machines, scrap_sinks)
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

        if quality_analysis['total_rework_attempts'] > 0:
            print(f"\nRework Summary:")
            print(f"  Total Attempts: {quality_analysis['total_rework_attempts']}")
            print(f"  Successes: {quality_analysis['total_rework_successes']}")
            rate = (quality_analysis['total_rework_successes']
                    / quality_analysis['total_rework_attempts'])
            print(f"  Success Rate: {rate:.1%}")
            for machine, rw in quality_analysis['rework_by_machine'].items():
                print(f"  {machine}: {rw['attempts']} attempts, "
                      f"{rw['successes']} successes")

        print("\nStopping server...")
    finally:
        # Flush and close historians
        if historian:
            historian.flush()
            historian.close()
            print(f"Event historian closed ({historian.get_event_count()} events recorded)")
        if neo4j_hist:
            neo4j_hist.close()
            print(f"Neo4j historian closed ({neo4j_hist.get_event_count()} events, {neo4j_hist._part_counter} parts)")
        server.stop()
        print("Server stopped.")


if __name__ == "__main__":
    main()
