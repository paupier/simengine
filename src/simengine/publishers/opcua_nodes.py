"""OPC UA node builders and write cache, lifted from the parent server (P6.2).

The ISA-95 address-space shape is preserved so parent-era OPC UA clients
(FactoryTalk Optix, UaExpert) browse identically. New in the clone: a
``ProcessValues/`` folder per station (one ``AnalogItemType`` per configured
PV, carrying EngineeringUnits + EURange) and ``ActiveReasonCode``/
``ActiveReasonText`` strings under each ``Alarms/`` node. Dropped from the
parent: SPC chart nodes and failure-mode stats nodes (replaced by reason
codes).

Stations and buffers are instances of the ``StationType`` /
``BufferStorageUnitType`` ObjectTypes declared here, so a client can bind one
screen to a type and reuse it across every station.

Writes are batched: ``CachedOpcuaNode`` appends dirty values to a shared
pending list; the publisher flushes the whole set once per publish (one
event-loop round-trip instead of hundreds — parent perf spec P2).
"""
from datetime import datetime

from asyncua import ua

_SENTINEL = object()

# ---------------------------------------------------------------------------
# NodeId roots — deliberately rename-invariant.
#
# BrowseNames still carry the full ISA-95 hierarchy (Acme > Plant1 > Area01 >
# Line1_Equipment > ...), so browsing is unchanged. NodeIds do NOT: they are
# what SCADA clients persist in their bindings, and deriving them from
# enterprise/site/area/line_name meant renaming any of those in the Configure
# tab silently invalidated every binding in every client project.
#
# Only one line is served per address space, so no line qualifier is needed.
# The functional group segment (OperationsState/OEE/ProcessValues/...) is kept
# rather than flattening to Station.<name>.<leaf>, because process value names
# come from user config and could otherwise collide with a metric name (a PV
# called "State" or "OEE" is legal).
# ---------------------------------------------------------------------------
NID_ENTERPRISE = "Enterprise"
NID_SITE = "Site"
NID_AREA = "Area"
NID_LINE = "Line"
NID_LINE_ASSET = "LineAsset"


def station_nid(name: str) -> str:
    return f"Station.{name}"


def station_asset_nid(name: str) -> str:
    return f"StationAsset.{name}"


def buffer_nid(name: str) -> str:
    return f"Buffer.{name}"


# "No alarm has occurred yet" — a fixed epoch, not datetime.now(). The node is
# never written by the publisher, so a now() default made every station report
# an alarm timestamp of server-boot-time forever, and made the exported
# NodeSet2 XML (api/schema.py) differ on every export.
_NO_ALARM_TIME = datetime(1970, 1, 1)

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


def _promote_to_analog_item(var, idx: int, node_prefix: str, unit: str,
                            eu_range) -> None:
    """Retype a plain variable as OPC UA ``AnalogItemType`` with real
    EngineeringUnits and EURange.

    Clients that render engineering units and default trend scaling (Optix,
    UaExpert) read these properties; a unit buried in the Description string
    is not machine-readable. EURange is mandatory on AnalogItemType, which is
    why callers only promote when a range is actually derivable.
    """
    var.delete_reference(ua.NodeId(ua.ObjectIds.BaseDataVariableType),
                         ua.NodeId(ua.ObjectIds.HasTypeDefinition))
    var.add_reference(ua.NodeId(ua.ObjectIds.AnalogItemType),
                      ua.NodeId(ua.ObjectIds.HasTypeDefinition))

    low, high = eu_range
    var.add_property(
        _nid(f"{node_prefix}.EURange", idx), ua.QualifiedName("EURange", 0),
        ua.Range(Low=low, High=high), ua.VariantType.ExtensionObject)
    var.add_property(
        _nid(f"{node_prefix}.EngineeringUnits", idx),
        ua.QualifiedName("EngineeringUnits", 0),
        ua.EUInformation(DisplayName=ua.LocalizedText(unit),
                         Description=ua.LocalizedText(unit)),
        ua.VariantType.ExtensionObject)


def create_process_values_node(parent_node, idx: int, pv_names_units: list,
                               node_prefix: str = ""):
    """ProcessValues/ folder: one Double variable per configured PV.

    PVs whose config yields a display range (see
    ``process_values.pv_display_range``) are modelled as AnalogItemType with
    EngineeringUnits + EURange; the rest stay plain variables carrying the
    unit in their Description.
    """
    p = node_prefix
    pv_node = parent_node.add_object(_nid(p, idx), _qn("ProcessValues", idx))
    vars_dict = {}
    for name, unit, eu_range in pv_names_units:
        nid = f"{p}.{name}"
        var = pv_node.add_variable(_nid(nid, idx), _qn(name, idx), 0.0)
        var.write_attribute(
            ua.AttributeIds.Description,
            ua.DataValue(ua.Variant(ua.LocalizedText(f"{name} [{unit}]"),
                                    ua.VariantType.LocalizedText)),
        )
        if eu_range is not None:
            _promote_to_analog_item(var, idx, nid, unit, eu_range)
        vars_dict[f"pv_{name}"] = var
    return vars_dict


# ---------------------------------------------------------------------------
# ObjectType declarations.
#
# Stations and buffers are instances of StationType / BufferStorageUnitType
# rather than bare BaseObjectType. That is what lets a SCADA client (Optix,
# Ignition) build ONE screen bound to the type and reuse it for every station,
# instead of a hand-built screen per station.
#
# The members are declared once here and instantiated by asyncua, which — when
# the instance has a String NodeId — derives child NodeIds as
# "<parent>.<BrowseName>" (instantiate_util.py). That is exactly the
# rename-invariant scheme in this module, so typing the nodes and keeping
# readable NodeIds are not in tension.
#
# Each entry: (group | None, browse name, default value, vars_dict key | None).
# The vars_dict key is what publishers/opcua_server.py writes through.
# ---------------------------------------------------------------------------
STATION_TYPE_NID = "StationType"
BUFFER_TYPE_NID = "BufferStorageUnitType"

_STATION_MEMBERS = (
    ("Identification", "EquipmentID", "", None),
    ("Identification", "EquipmentClass", "WorkCell", None),
    ("Identification", "Description", "", None),

    ("OperationsState", "State", "IDLE", "state"),
    ("OperationsState", "CyclePhase", 0.0, "cycle_phase"),

    ("OperationsPerformance", "PartCount", 0, "partcount"),
    ("OperationsPerformance", "ScrapCount", 0, "scrap_count"),
    ("OperationsPerformance", "ReworkCount", 0, "rework_count"),
    ("OperationsPerformance", "BlockedTime", 0.0, "blocked_time"),
    ("OperationsPerformance", "StarvedTime", 0.0, "starved_time"),
    ("OperationsPerformance", "DownTime", 0.0, "down_time"),
    ("OperationsPerformance", "ProcessingTime", 0.0, "processing_time"),
    ("OperationsPerformance", "IdleTime", 0.0, "idle_time"),
    ("OperationsPerformance", "MinorStopTime", 0.0, "minor_stop_time"),

    ("OEE", "Availability", 0.0, "availability"),
    ("OEE", "Performance", 0.0, "performance"),
    ("OEE", "Quality", 1.0, "quality"),
    ("OEE", "OEE", 0.0, "oee"),
    ("OEE", "GoodPartCount", 0, "good_parts"),
    ("OEE", "DefectivePartCount", 0, "defective_parts"),

    ("Alarms", "ActiveAlarmCount", 0, "alarm_alarm_count"),
    ("Alarms", "LastAlarmTime", _NO_ALARM_TIME, "alarm_last_alarm_time"),
    ("Alarms", "LastAlarmMessage", "", "alarm_last_alarm_message"),
    ("Alarms", "LastAlarmSeverity", "", "alarm_last_alarm_severity"),
    ("Alarms", "ActiveReasonCode", "", "alarm_reason_code"),
    ("Alarms", "ActiveReasonText", "", "alarm_reason_text"),
    ("Alarms", "MachineFailureActive", False, "alarm_alarm_failure"),
    ("Alarms", "MaintenanceActive", False, "alarm_alarm_maintenance"),
    ("Alarms", "QualityAlertActive", False, "alarm_alarm_quality"),
)

# Only present when the station configures a health model, so declared with the
# Optional modelling rule and instantiated per station.
_STATION_OPTIONAL_MEMBERS = (
    ("OperationsState", "HealthState", 0, "health"),
    ("OperationsState", "HealthPercent", 100.0, "health_pct"),
)

_BUFFER_MEMBERS = (
    (None, "CurrentLevel", 0, "level"),
    (None, "Capacity", 0, "capacity"),

    ("Alarms", "ActiveAlarmCount", 0, "alarm_alarm_count"),
    ("Alarms", "LastAlarmTime", _NO_ALARM_TIME, "alarm_last_alarm_time"),
    ("Alarms", "LastAlarmMessage", "", "alarm_last_alarm_message"),
    ("Alarms", "LastAlarmSeverity", "", "alarm_last_alarm_severity"),
    ("Alarms", "HighLevelWarningActive", False, "alarm_alarm_high"),
    ("Alarms", "LowLevelWarningActive", False, "alarm_alarm_low"),
)


def _declare_object_type(server, idx: int, type_nid: str, type_name: str,
                         members, optional_members=()):
    """Declare one ObjectType with its members and modelling rules."""
    base = server.get_node(ua.NodeId(ua.ObjectIds.BaseObjectType))
    type_node = base.add_object_type(_nid(type_nid, idx), _qn(type_name, idx))

    groups = {}

    def group_node(group):
        if group is None:
            return type_node
        if group not in groups:
            node = type_node.add_object(
                _nid(f"{type_nid}.{group}", idx), _qn(group, idx))
            node.set_modelling_rule(True)
            groups[group] = node
        return groups[group]

    def declare(member_list, mandatory):
        for group, name, default, _key in member_list:
            parent = group_node(group)
            path = f"{type_nid}.{group}.{name}" if group else f"{type_nid}.{name}"
            var = parent.add_variable(_nid(path, idx), _qn(name, idx), default)
            var.set_modelling_rule(mandatory)

    declare(members, True)
    declare(optional_members, False)
    return type_node


def declare_object_types(server, idx: int) -> dict:
    """Declare StationType and BufferStorageUnitType once per address space."""
    return {
        "station": _declare_object_type(
            server, idx, STATION_TYPE_NID, "StationType",
            _STATION_MEMBERS, _STATION_OPTIONAL_MEMBERS),
        "buffer": _declare_object_type(
            server, idx, BUFFER_TYPE_NID, "BufferStorageUnitType",
            _BUFFER_MEMBERS),
    }


def _collect_instance_vars(server, idx: int, node_prefix: str, members):
    """Map vars_dict keys to the instantiated child nodes by NodeId.

    Safe because asyncua derives instance child NodeIds as
    "<parent>.<BrowseName>" for string-id parents — the same paths declared on
    the type.
    """
    out = {}
    for group, name, _default, key in members:
        if key is None:
            continue
        path = (f"{node_prefix}.{group}.{name}" if group
                else f"{node_prefix}.{name}")
        out[key] = server.get_node(ua.NodeId(path, idx))
    return out


def create_station_node(server, parent_node, idx: int, station_name: str,
                        enable_health: bool = False,
                        pv_names_units: list = None,
                        node_prefix: str = "", station_type=None):
    """ISA-95 Equipment node for one station, instantiated from StationType."""
    p = node_prefix
    st_node = parent_node.add_object(
        _nid(p, idx), _qn(f"{station_name}_Equipment", idx),
        objecttype=station_type, instantiate_optional=enable_health)

    members = _STATION_MEMBERS + (_STATION_OPTIONAL_MEMBERS if enable_health else ())
    vars_dict = _collect_instance_vars(server, idx, p, members)

    # Per-station identification values (the type carries only defaults).
    server.get_node(
        ua.NodeId(f"{p}.Identification.EquipmentID", idx)).set_value(station_name)
    server.get_node(
        ua.NodeId(f"{p}.Identification.Description", idx)
    ).set_value(f"Station {station_name}")

    # Process values are per-station, so they are added to the instance rather
    # than declared on the type (an instance may have extra components).
    if pv_names_units:
        vars_dict.update(create_process_values_node(
            st_node, idx, pv_names_units, node_prefix=f"{p}.ProcessValues"))

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


def create_storage_unit_node(server, parent_node, idx: int, unit_name: str,
                             capacity: int, node_prefix: str = "",
                             buffer_type=None):
    """ISA-95 StorageUnit node for a buffer, instantiated from
    BufferStorageUnitType.

    Capacity is a type member and so always present; a negative value means
    unbounded (previously the node was omitted entirely in that case).
    """
    p = node_prefix
    parent_node.add_object(_nid(p, idx), _qn(unit_name, idx),
                           objecttype=buffer_type)
    vars_dict = _collect_instance_vars(server, idx, p, _BUFFER_MEMBERS)
    vars_dict["capacity"].set_value(capacity)
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
