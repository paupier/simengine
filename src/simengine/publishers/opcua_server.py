"""OPC UA TCP server publisher (build plan P6.2).

Builds the ISA-95 address space from the scenario config (same shape as the
parent server) and writes each ``LineSnapshot`` through the CachedOpcuaNode
dirty-set, flushed as one batched write per publish under a single
address-space lock acquisition (parent perf spec P2).
"""
import logging

from opcua import Server, ua

from simengine.publishers import StatePublisher
from simengine.publishers.opcua_nodes import (
    _nid,
    _qn,
    create_shift_management_node,
    create_station_asset_node,
    create_station_node,
    create_storage_unit_node,
    wrap_opcua_vars_with_cache,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# python-opcua compatibility patches carried from the parent (FactoryTalk
# Optix refuses abstract reference types / blocked HasSubtype browsing).
# ---------------------------------------------------------------------------
_original_reftype_init = ua.uaprotocol_auto.ReferenceTypeAttributes.__init__


def _patched_reftype_init(self):
    _original_reftype_init(self)
    self.IsAbstract = False
    self.Symmetric = False


ua.uaprotocol_auto.ReferenceTypeAttributes.__init__ = _patched_reftype_init

from opcua.server.address_space import ViewService as _ViewService  # noqa: E402


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


class OPCUAServerPublisher(StatePublisher):
    """ISA-95 OPC UA TCP server fed from LineSnapshot."""

    def __init__(self, config: dict, port: int = 4840):
        self.config = config
        self.port = port
        self.server = None
        self.opcua_vars = {}
        self.pending_writes = []
        self._started = False

    # ----- address space -----

    def _build(self, snapshot) -> None:
        config = self.config
        enterprise = config.get("enterprise", "Enterprise")
        site = config.get("site", "Site")
        area = config.get("area", "Area")
        line = config.get("line_name", "Line1")

        self.server = Server()
        self.server.set_endpoint(f"opc.tcp://0.0.0.0:{self.port}/simengine/")
        self.server.set_server_name("simengine Station Simulation")
        idx = self.server.register_namespace("http://simengine.local/")

        objects = self.server.get_objects_node()
        ent_node = objects.add_object(_nid(enterprise, idx), _qn(enterprise, idx))
        site_node = ent_node.add_object(_nid(f"{enterprise}.{site}", idx), _qn(site, idx))
        area_node = site_node.add_object(
            _nid(f"{enterprise}.{site}.{area}", idx), _qn(area, idx))

        prefix = f"{enterprise}.{site}.{area}.{line}_Equipment"
        line_node = area_node.add_object(_nid(prefix, idx), _qn(f"{line}_Equipment", idx))

        v = self.opcua_vars

        # Identification
        id_p = f"{prefix}.Identification"
        id_node = line_node.add_object(_nid(id_p, idx), _qn("Identification", idx))
        id_node.add_variable(_nid(f"{id_p}.EquipmentID", idx), _qn("EquipmentID", idx), line)
        id_node.add_variable(_nid(f"{id_p}.EquipmentClass", idx), _qn("EquipmentClass", idx), "ProductionLine")
        id_node.add_variable(_nid(f"{id_p}.Description", idx), _qn("Description", idx),
                             config.get("description", f"Line {line}"))
        id_node.add_variable(_nid(f"{id_p}.RunID", idx), _qn("RunID", idx), snapshot.run_id)

        # OperationsState
        os_p = f"{prefix}.OperationsState"
        os_node = line_node.add_object(_nid(os_p, idx), _qn("OperationsState", idx))
        v["system"] = {
            "simtime": os_node.add_variable(_nid(f"{os_p}.SimTime", idx), _qn("SimTime", idx), 0.0),
            "line_state": os_node.add_variable(_nid(f"{os_p}.LineState", idx), _qn("LineState", idx), "RUNNING"),
        }
        ctrl_p = f"{os_p}.Controls"
        ctrl_node = os_node.add_object(_nid(ctrl_p, idx), _qn("Controls", idx))
        ctrl_node.add_variable(_nid(f"{ctrl_p}.SimSpeedRatio", idx),
                               _qn("SimSpeedRatio", idx), snapshot.speed_ratio)

        # OperationsPerformance
        op_p = f"{prefix}.OperationsPerformance"
        op_node = line_node.add_object(_nid(op_p, idx), _qn("OperationsPerformance", idx))
        v["line_kpis"] = {
            "throughput": op_node.add_variable(_nid(f"{op_p}.Throughput", idx), _qn("Throughput", idx), 0.0),
            "total_wip": op_node.add_variable(_nid(f"{op_p}.TotalWIP", idx), _qn("TotalWIP", idx), 0),
            "total_scrap": op_node.add_variable(_nid(f"{op_p}.TotalScrap", idx), _qn("TotalScrap", idx), 0),
        }

        # Line OEE
        oee_p = f"{prefix}.OEE"
        oee_node = line_node.add_object(_nid(oee_p, idx), _qn("OEE", idx))
        v["line_oee"] = {
            "line_oee": oee_node.add_variable(_nid(f"{oee_p}.OEE", idx), _qn("OEE", idx), 0.0),
            "line_good_parts": oee_node.add_variable(_nid(f"{oee_p}.GoodPartCount", idx), _qn("GoodPartCount", idx), 0),
        }

        # Resources: stations + buffers
        res_p = f"{prefix}.Resources"
        res_node = line_node.add_object(_nid(res_p, idx), _qn("Resources", idx))
        v["stations"] = {}
        for st_cfg in config["stations"]:
            name = st_cfg["name"]
            pv_units = [(pv["name"], pv["unit"]) for pv in st_cfg.get("process_values", [])]
            v["stations"][name] = create_station_node(
                res_node, idx, name,
                enable_health="health" in st_cfg,
                pv_names_units=pv_units,
                node_prefix=f"{res_p}.{name}_Equipment",
            )
            create_station_asset_node(res_node, idx, name,
                                      node_prefix=f"{res_p}.{name}_Asset")

        v["buffers"] = {}
        for b_cfg in config["buffers"]:
            bname = b_cfg["name"]
            v["buffers"][bname] = create_storage_unit_node(
                res_node, idx, f"{bname}_StorageUnit", b_cfg["capacity"],
                node_prefix=f"{res_p}.{bname}_StorageUnit",
            )

        # SupportFunctions (shift nodes only when shifts configured)
        if config.get("shifts", {}).get("schedule"):
            sf_p = f"{prefix}.SupportFunctions"
            sf_node = line_node.add_object(_nid(sf_p, idx), _qn("SupportFunctions", idx))
            v["shift"] = create_shift_management_node(
                sf_node, idx, node_prefix=f"{sf_p}.ShiftManagement")

        # Line asset node
        asset_p = f"{enterprise}.{site}.{area}.{line}_Asset"
        asset_node = area_node.add_object(_nid(asset_p, idx), _qn(f"{line}_Asset", idx))
        aid_p = f"{asset_p}.Identification"
        aid_node = asset_node.add_object(_nid(aid_p, idx), _qn("Identification", idx))
        aid_node.add_variable(_nid(f"{aid_p}.PhysicalAssetID", idx), _qn("PhysicalAssetID", idx), f"{line}_Asset")
        aid_node.add_variable(_nid(f"{aid_p}.AssetClass", idx), _qn("AssetClass", idx), "ProductionLine")

        wrap_opcua_vars_with_cache(v, pending=self.pending_writes)

    # ----- publisher lifecycle -----

    def on_run_start(self, snapshot) -> None:
        self._build(snapshot)
        self.server.start()
        self._started = True
        logger.info("OPC UA server started at opc.tcp://0.0.0.0:%s/simengine/", self.port)

    def publish(self, snapshot) -> None:
        v = self.opcua_vars
        v["system"]["simtime"].set_value(snapshot.sim_time)
        v["system"]["line_state"].set_value(snapshot.line_state)
        v["line_kpis"]["throughput"].set_value(snapshot.throughput)
        v["line_kpis"]["total_wip"].set_value(snapshot.total_wip)
        v["line_kpis"]["total_scrap"].set_value(snapshot.total_scrap)
        v["line_oee"]["line_oee"].set_value(snapshot.oee)
        v["line_oee"]["line_good_parts"].set_value(snapshot.total_good)

        for name, st in snapshot.stations.items():
            sv = v["stations"].get(name)
            if sv is None:
                continue
            sv["state"].set_value(st.state)
            if "health" in sv:
                sv["health"].set_value(st.health)
                sv["health_pct"].set_value(
                    100.0 * (1.0 - st.health / st.h_max) if st.h_max else 100.0)
            sv["cycle_phase"].set_value(st.cycle_phase)
            sv["partcount"].set_value(st.parts_made)
            sv["scrap_count"].set_value(st.scrap)
            sv["rework_count"].set_value(st.rework)
            tis = st.time_in_state
            sv["blocked_time"].set_value(tis.get("BLOCKED", 0.0))
            sv["starved_time"].set_value(tis.get("STARVED", 0.0))
            sv["down_time"].set_value(
                tis.get("FAILED", 0.0) + tis.get("UNDER_REPAIR", 0.0))
            sv["processing_time"].set_value(
                tis.get("PROCESSING", 0.0) + tis.get("DEGRADED", 0.0))
            sv["idle_time"].set_value(tis.get("IDLE", 0.0))
            sv["minor_stop_time"].set_value(tis.get("MINOR_STOP", 0.0))
            sv["availability"].set_value(st.availability)
            sv["performance"].set_value(st.performance)
            sv["quality"].set_value(st.quality)
            sv["oee"].set_value(st.oee)
            sv["good_parts"].set_value(st.good)
            sv["defective_parts"].set_value(st.defective)

            # Alarms: reason code = highest severity active (ties: most recent)
            alarms = st.alarms
            sv["alarm_alarm_count"].set_value(len(alarms))
            if alarms:
                top = max(alarms, key=lambda a: (
                    {"CRITICAL": 3, "HIGH": 2, "WARNING": 1, "INFO": 0}.get(a.severity, -1),
                    a.activated_at))
                sv["alarm_reason_code"].set_value(top.code)
                sv["alarm_reason_text"].set_value(top.text)
                sv["alarm_last_alarm_message"].set_value(top.text)
                sv["alarm_last_alarm_severity"].set_value(top.severity)
            else:
                sv["alarm_reason_code"].set_value("")
                sv["alarm_reason_text"].set_value("")
            sv["alarm_alarm_failure"].set_value(
                any(a.code.startswith("FM_") for a in alarms))
            sv["alarm_alarm_maintenance"].set_value(
                any(a.code.startswith("MT_") for a in alarms))
            sv["alarm_alarm_quality"].set_value(
                any(a.code.startswith("PV_") for a in alarms))

            for pv in st.process_values:
                key = f"pv_{pv.name}"
                if key in sv:
                    sv[key].set_value(pv.value)

        for bname, buf in snapshot.buffers.items():
            bv = v["buffers"].get(bname)
            if bv is None:
                continue
            bv["level"].set_value(buf.level)
            bv["alarm_alarm_high"].set_value(buf.level >= buf.capacity)
            bv["alarm_alarm_low"].set_value(buf.level == 0)

        if snapshot.shift and "shift" in v:
            sh = snapshot.shift
            shv = v["shift"]
            shv["shift_number"].set_value(sh.get("shift_number", 1))
            shv["shift_name"].set_value(sh.get("shift_name", ""))
            shv["shift_elapsed"].set_value(sh.get("shift_elapsed", 0.0))
            shv["shift_remaining"].set_value(sh.get("shift_remaining", 0.0))
            shv["current_parts"].set_value(sh.get("parts_produced", 0))
            shv["current_good"].set_value(sh.get("good_parts", 0))

        self._flush()

    def _flush(self) -> None:
        """One batched write for the whole dirty set: single lock acquisition."""
        if not self.pending_writes or self.server is None:
            return
        iserver = self.server.iserver
        aspace = iserver.aspace
        with aspace._lock:  # RLock: inner acquisitions are re-entrant
            for node, value, vtype in self.pending_writes:
                variant = ua.Variant(value, vtype) if vtype else ua.Variant(value)
                iserver.set_attribute_value(node.nodeid, ua.DataValue(variant))
        self.pending_writes.clear()

    def on_run_end(self) -> None:
        if self.opcua_vars.get("system"):
            self.opcua_vars["system"]["line_state"].set_value("STOPPED")
            self._flush()

    def close(self) -> None:
        if self._started and self.server is not None:
            try:
                self.server.stop()
            except Exception:  # pragma: no cover - shutdown best-effort
                logger.exception("OPC UA server stop failed")
            self._started = False
