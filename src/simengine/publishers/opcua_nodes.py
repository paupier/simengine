"""OPC UA node builders and write cache, lifted from the parent server (P6.2).

The ISA-95 address-space shape is preserved so parent-era OPC UA clients
(FactoryTalk Optix, UaExpert) browse identically. New in the clone: a
``ProcessValues/`` folder per station (one Float per configured PV) and
``ActiveReasonCode``/``ActiveReasonText`` strings under each ``Alarms/`` node.
Dropped from the parent: SPC chart nodes and failure-mode stats nodes
(replaced by reason codes).

Writes are batched: ``CachedOpcuaNode`` appends dirty values to a shared
pending list; the publisher flushes the whole set once per publish
(one lock acquisition instead of hundreds — parent perf spec P2).
"""
from datetime import datetime

from opcua import ua

_SENTINEL = object()

# Dead-band mapping — float keys that drift by tiny increments each step.
_OEE_FLOAT_KEYS = frozenset([
    "availability", "performance", "quality", "oee", "utilisation",
    "health_pct", "line_availability", "line_performance", "line_quality",
    "line_oee", "scrap_rate", "throughput",
])
_TIME_ACC_KEYS = frozenset([
    "blocked_time", "starved_time", "down_time", "processing_time", "idle_time",
    "minor_stop_time", "shift_total_time",
])


def _get_dead_band_for_key(key: str):
    """Dead-band per opcua_vars key; None = exact-equality caching."""
    if key in _OEE_FLOAT_KEYS:
        return 0.001
    if key in _TIME_ACC_KEYS:
        return 5.0
    if key.startswith("pv_"):
        return None  # process values write on any change (dead-band via noise floor)
    return None


def _nid(path, idx):
    """Explicit string NodeId from a dot-separated path (stable, readable)."""
    return ua.NodeId(path, idx)


def _qn(name, idx):
    """QualifiedName with the application namespace for BrowseName navigation."""
    return ua.QualifiedName(name, idx)


class CachedOpcuaNode:
    """Write-on-change wrapper; dirty values go to a shared pending list.

    Dead-band suppresses writes for slowly-drifting floats. When ``pending``
    is provided, changed values are appended as (node, value, variant_type)
    for a single batched flush per publish instead of immediate set_value().
    """

    __slots__ = ("_node", "_cached_value", "_dead_band", "_pending", "_vtype")

    def __init__(self, node, dead_band=None, pending=None, variant_type=None):
        self._node = node
        self._cached_value = _SENTINEL
        self._dead_band = dead_band
        self._pending = pending
        self._vtype = variant_type

    def _write(self, value):
        if self._pending is not None:
            self._pending.append((self._node, value, self._vtype))
        else:
            self._node.set_value(value)
        self._cached_value = value

    def set_value(self, value):
        if self._cached_value is _SENTINEL:
            self._write(value)
            return
        if self._dead_band is not None:
            try:
                if abs(value - self._cached_value) < self._dead_band:
                    return
            except TypeError:
                pass
        if value is not self._cached_value:
            try:
                if value != self._cached_value:
                    self._write(value)
            except Exception:
                self._write(value)

    def get_value(self):
        return self._node.get_value()

    def __getattr__(self, name):
        return getattr(self._node, name)


def wrap_opcua_vars_with_cache(d, pending=None):
    """Recursively wrap node objects in a nested dict with CachedOpcuaNode."""
    for k, v in d.items():
        if isinstance(v, dict):
            wrap_opcua_vars_with_cache(v, pending)
        elif hasattr(v, "set_value") and not isinstance(v, CachedOpcuaNode):
            vtype = None
            try:
                vtype = v.get_data_type_as_variant_type()
            except Exception:
                pass
            d[k] = CachedOpcuaNode(
                v, dead_band=_get_dead_band_for_key(k), pending=pending,
                variant_type=vtype,
            )


def create_alarms_node(parent_node, idx: int, alarm_type: str = "machine",
                       node_prefix: str = ""):
    """Alarms sub-node: reason codes + parent-compatible booleans."""
    p = node_prefix
    alarms_node = parent_node.add_object(_nid(p, idx), _qn("Alarms", idx))

    vars_dict = {}
    vars_dict["alarm_count"] = alarms_node.add_variable(
        _nid(f"{p}.ActiveAlarmCount", idx), _qn("ActiveAlarmCount", idx), 0)
    vars_dict["last_alarm_time"] = alarms_node.add_variable(
        _nid(f"{p}.LastAlarmTime", idx), _qn("LastAlarmTime", idx), datetime.now())
    vars_dict["last_alarm_message"] = alarms_node.add_variable(
        _nid(f"{p}.LastAlarmMessage", idx), _qn("LastAlarmMessage", idx), "")
    vars_dict["last_alarm_severity"] = alarms_node.add_variable(
        _nid(f"{p}.LastAlarmSeverity", idx), _qn("LastAlarmSeverity", idx), "")

    if alarm_type == "machine":
        vars_dict["reason_code"] = alarms_node.add_variable(
            _nid(f"{p}.ActiveReasonCode", idx), _qn("ActiveReasonCode", idx), "")
        vars_dict["reason_text"] = alarms_node.add_variable(
            _nid(f"{p}.ActiveReasonText", idx), _qn("ActiveReasonText", idx), "")
        vars_dict["alarm_failure"] = alarms_node.add_variable(
            _nid(f"{p}.MachineFailureActive", idx), _qn("MachineFailureActive", idx), False)
        vars_dict["alarm_maintenance"] = alarms_node.add_variable(
            _nid(f"{p}.MaintenanceActive", idx), _qn("MaintenanceActive", idx), False)
        vars_dict["alarm_quality"] = alarms_node.add_variable(
            _nid(f"{p}.QualityAlertActive", idx), _qn("QualityAlertActive", idx), False)
    elif alarm_type == "buffer":
        vars_dict["alarm_high"] = alarms_node.add_variable(
            _nid(f"{p}.HighLevelWarningActive", idx), _qn("HighLevelWarningActive", idx), False)
        vars_dict["alarm_low"] = alarms_node.add_variable(
            _nid(f"{p}.LowLevelWarningActive", idx), _qn("LowLevelWarningActive", idx), False)

    return vars_dict


def create_process_values_node(parent_node, idx: int, pv_names_units: list,
                               node_prefix: str = ""):
    """ProcessValues/ folder: one Float variable per configured PV."""
    p = node_prefix
    pv_node = parent_node.add_object(_nid(p, idx), _qn("ProcessValues", idx))
    vars_dict = {}
    for name, unit in pv_names_units:
        var = pv_node.add_variable(
            _nid(f"{p}.{name}", idx), _qn(name, idx), 0.0)
        var.set_attribute(
            ua.AttributeIds.Description,
            ua.DataValue(ua.LocalizedText(f"{name} [{unit}]")),
        )
        vars_dict[f"pv_{name}"] = var
    return vars_dict


def create_station_node(parent_node, idx: int, station_name: str,
                        enable_health: bool = False,
                        pv_names_units: list = None,
                        node_prefix: str = ""):
    """ISA-95 Equipment node for one station ({name}_Equipment)."""
    p = node_prefix
    node_name = f"{station_name}_Equipment"
    st_node = parent_node.add_object(_nid(p, idx), _qn(node_name, idx))

    vars_dict = {}

    id_p = f"{p}.Identification"
    id_node = st_node.add_object(_nid(id_p, idx), _qn("Identification", idx))
    id_node.add_variable(_nid(f"{id_p}.EquipmentID", idx), _qn("EquipmentID", idx), station_name)
    id_node.add_variable(_nid(f"{id_p}.EquipmentClass", idx), _qn("EquipmentClass", idx), "WorkCell")
    id_node.add_variable(_nid(f"{id_p}.Description", idx), _qn("Description", idx), f"Station {station_name}")

    os_p = f"{p}.OperationsState"
    ops_state = st_node.add_object(_nid(os_p, idx), _qn("OperationsState", idx))
    vars_dict["state"] = ops_state.add_variable(_nid(f"{os_p}.State", idx), _qn("State", idx), "IDLE")
    if enable_health:
        vars_dict["health"] = ops_state.add_variable(
            _nid(f"{os_p}.HealthState", idx), _qn("HealthState", idx), 0)
        vars_dict["health_pct"] = ops_state.add_variable(
            _nid(f"{os_p}.HealthPercent", idx), _qn("HealthPercent", idx), 100.0)
    vars_dict["cycle_phase"] = ops_state.add_variable(
        _nid(f"{os_p}.CyclePhase", idx), _qn("CyclePhase", idx), 0.0)

    op_p = f"{p}.OperationsPerformance"
    ops_perf = st_node.add_object(_nid(op_p, idx), _qn("OperationsPerformance", idx))
    vars_dict["partcount"] = ops_perf.add_variable(_nid(f"{op_p}.PartCount", idx), _qn("PartCount", idx), 0)
    vars_dict["scrap_count"] = ops_perf.add_variable(_nid(f"{op_p}.ScrapCount", idx), _qn("ScrapCount", idx), 0)
    vars_dict["rework_count"] = ops_perf.add_variable(_nid(f"{op_p}.ReworkCount", idx), _qn("ReworkCount", idx), 0)
    vars_dict["blocked_time"] = ops_perf.add_variable(_nid(f"{op_p}.BlockedTime", idx), _qn("BlockedTime", idx), 0.0)
    vars_dict["starved_time"] = ops_perf.add_variable(_nid(f"{op_p}.StarvedTime", idx), _qn("StarvedTime", idx), 0.0)
    vars_dict["down_time"] = ops_perf.add_variable(_nid(f"{op_p}.DownTime", idx), _qn("DownTime", idx), 0.0)
    vars_dict["processing_time"] = ops_perf.add_variable(_nid(f"{op_p}.ProcessingTime", idx), _qn("ProcessingTime", idx), 0.0)
    vars_dict["idle_time"] = ops_perf.add_variable(_nid(f"{op_p}.IdleTime", idx), _qn("IdleTime", idx), 0.0)
    vars_dict["minor_stop_time"] = ops_perf.add_variable(_nid(f"{op_p}.MinorStopTime", idx), _qn("MinorStopTime", idx), 0.0)

    oee_p = f"{p}.OEE"
    oee_node = st_node.add_object(_nid(oee_p, idx), _qn("OEE", idx))
    vars_dict["availability"] = oee_node.add_variable(_nid(f"{oee_p}.Availability", idx), _qn("Availability", idx), 0.0)
    vars_dict["performance"] = oee_node.add_variable(_nid(f"{oee_p}.Performance", idx), _qn("Performance", idx), 0.0)
    vars_dict["quality"] = oee_node.add_variable(_nid(f"{oee_p}.Quality", idx), _qn("Quality", idx), 1.0)
    vars_dict["oee"] = oee_node.add_variable(_nid(f"{oee_p}.OEE", idx), _qn("OEE", idx), 0.0)
    vars_dict["good_parts"] = oee_node.add_variable(_nid(f"{oee_p}.GoodPartCount", idx), _qn("GoodPartCount", idx), 0)
    vars_dict["defective_parts"] = oee_node.add_variable(_nid(f"{oee_p}.DefectivePartCount", idx), _qn("DefectivePartCount", idx), 0)

    alarm_vars = create_alarms_node(st_node, idx, alarm_type="machine",
                                    node_prefix=f"{p}.Alarms")
    vars_dict.update({f"alarm_{k}": v for k, v in alarm_vars.items()})

    if pv_names_units:
        pv_vars = create_process_values_node(
            st_node, idx, pv_names_units, node_prefix=f"{p}.ProcessValues")
        vars_dict.update(pv_vars)

    return vars_dict


def create_station_asset_node(parent_node, idx: int, station_name: str,
                              node_prefix: str = ""):
    """ISA-95 PhysicalAsset node ({name}_Asset) — static identification."""
    p = node_prefix
    node_name = f"{station_name}_Asset"
    asset_node = parent_node.add_object(_nid(p, idx), _qn(node_name, idx))
    id_p = f"{p}.Identification"
    id_node = asset_node.add_object(_nid(id_p, idx), _qn("Identification", idx))
    id_node.add_variable(_nid(f"{id_p}.PhysicalAssetID", idx), _qn("PhysicalAssetID", idx), node_name)
    id_node.add_variable(_nid(f"{id_p}.AssetClass", idx), _qn("AssetClass", idx), "Machine")
    id_node.add_variable(_nid(f"{id_p}.Vendor", idx), _qn("Vendor", idx), "Generic")
    id_node.add_variable(_nid(f"{id_p}.Model", idx), _qn("Model", idx), "StandardStation")
    id_node.add_variable(_nid(f"{id_p}.SerialNumber", idx), _qn("SerialNumber", idx), f"SN-{station_name}-001")
    return {}


def create_storage_unit_node(parent_node, idx: int, unit_name: str, capacity: int,
                             node_prefix: str = "", include_alarms: bool = True):
    """ISA-95 StorageUnit node for a buffer."""
    p = node_prefix
    unit_node = parent_node.add_object(_nid(p, idx), _qn(unit_name, idx))
    vars_dict = {}
    vars_dict["level"] = unit_node.add_variable(
        _nid(f"{p}.CurrentLevel", idx), _qn("CurrentLevel", idx), 0)
    if capacity >= 0:
        vars_dict["capacity"] = unit_node.add_variable(
            _nid(f"{p}.Capacity", idx), _qn("Capacity", idx), capacity)
    if include_alarms:
        alarm_vars = create_alarms_node(unit_node, idx, alarm_type="buffer",
                                        node_prefix=f"{p}.Alarms")
        vars_dict.update({f"alarm_{k}": v for k, v in alarm_vars.items()})
    return vars_dict


def create_shift_management_node(parent_node, idx: int, node_prefix: str = ""):
    """ShiftManagement sub-node under SupportFunctions (carried from parent)."""
    p = node_prefix
    shift_node = parent_node.add_object(_nid(p, idx), _qn("ShiftManagement", idx))
    vars_dict = {}
    vars_dict["shift_number"] = shift_node.add_variable(
        _nid(f"{p}.CurrentShiftNumber", idx), _qn("CurrentShiftNumber", idx), 1)
    vars_dict["shift_name"] = shift_node.add_variable(
        _nid(f"{p}.CurrentShiftName", idx), _qn("CurrentShiftName", idx), "")
    vars_dict["shift_elapsed"] = shift_node.add_variable(
        _nid(f"{p}.ShiftElapsedTime", idx), _qn("ShiftElapsedTime", idx), 0.0)
    vars_dict["shift_remaining"] = shift_node.add_variable(
        _nid(f"{p}.ShiftTimeRemaining", idx), _qn("ShiftTimeRemaining", idx), 0.0)
    vars_dict["current_parts"] = shift_node.add_variable(
        _nid(f"{p}.CurrentShiftParts", idx), _qn("CurrentShiftParts", idx), 0)
    vars_dict["current_good"] = shift_node.add_variable(
        _nid(f"{p}.CurrentShiftGoodParts", idx), _qn("CurrentShiftGoodParts", idx), 0)
    return vars_dict
