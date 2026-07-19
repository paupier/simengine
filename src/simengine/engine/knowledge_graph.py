"""Knowledge graph of the data model (AI interface spec §1, stdlib-only).

Built deterministically at run start from the scenario config + comms config.
It is the semantic registry of everything the engine models and publishes:
the ISA-95 hierarchy, material flow, per-station process values / failure
modes / alarm codes, and — the load-bearing feature — every ProcessValue and
Metric node carries all of its wire addresses (OPC UA NodeId, SparkplugB
metric coordinates, flat MQTT topic, REST JSON path). The KG is the single
place that binds the three protocols' addressing schemes.

Same scenario config => byte-identical node-link JSON.
"""
from typing import Dict, List, Optional

from simengine.engine import alarms as alarm_defs
from simengine.publishers.opcua_mqtt import flat_topic

NODE_TYPES = (
    "Enterprise", "Site", "Area", "Line", "Station", "Buffer", "ProcessValue",
    "FailureMode", "AlarmCode", "CycleStopReason", "Scenario", "Recipe", "Metric",
)

EDGE_TYPES = ("CONTAINS", "FEEDS", "HAS_PV", "HAS_FAILURE_MODE", "CAN_RAISE",
              "MEASURED_BY", "RUNS")

# Station metric names published on every protocol (see publishers/metrics.py)
STATION_METRIC_NAMES = (
    "State", "Health", "PartsMade", "Good", "Scrap",
    "OEE", "Availability", "Performance", "Quality", "ActiveReasonCode",
)


class KnowledgeGraph:
    """Plain dict adjacency — no networkx (lean-core rule)."""

    def __init__(self):
        self.nodes: Dict[str, dict] = {}
        self.edges: List[dict] = []

    def add_node(self, node_id: str, node_type: str, **attrs) -> dict:
        node = {"id": node_id, "type": node_type, **attrs}
        self.nodes[node_id] = node
        return node

    def add_edge(self, source: str, target: str, edge_type: str) -> None:
        self.edges.append({"source": source, "target": target, "type": edge_type})

    # ----- queries -----

    def find_nodes(self, node_type: Optional[str] = None,
                   station: Optional[str] = None,
                   name: Optional[str] = None) -> List[dict]:
        out = []
        for node in self.nodes.values():
            if node_type and node["type"] != node_type:
                continue
            if station and node.get("station") != station and node.get("name") != station:
                continue
            if name and node.get("name") != name:
                continue
            out.append(node)
        return out

    def find_edges(self, edge_type: Optional[str] = None) -> List[dict]:
        if edge_type is None:
            return list(self.edges)
        return [e for e in self.edges if e["type"] == edge_type]

    def neighbors(self, node_id: str, edge_type: Optional[str] = None) -> List[dict]:
        out = []
        for e in self.edges:
            if edge_type and e["type"] != edge_type:
                continue
            if e["source"] == node_id:
                out.append(self.nodes[e["target"]])
            elif e["target"] == node_id:
                out.append(self.nodes[e["source"]])
        return out

    def to_node_link(self, node_type: Optional[str] = None,
                     station: Optional[str] = None,
                     edge: Optional[str] = None) -> dict:
        nodes = self.find_nodes(node_type=node_type, station=station)
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in self.find_edges(edge_type=edge)
                 if not (node_type or station)
                 or (e["source"] in node_ids or e["target"] in node_ids)]
        return {"nodes": nodes, "edges": edges}

    def resolve(self, query: str) -> List[dict]:
        """Lexical semantic lookup: match query terms against node names.

        "oil temperature on the press" -> pv:Press01.OilTemp (best-first).
        """
        terms = [t for t in query.lower().replace(".", " ").split() if len(t) > 2]
        scored = []
        for node in self.nodes.values():
            hay = " ".join(str(node.get(k, "")) for k in
                           ("id", "name", "station", "unit", "type")).lower()
            score = sum(1 for t in terms if t in hay)
            if score:
                scored.append((score, node["id"], node))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [n for _, _, n in scored]


def build_knowledge_graph(config: dict, scenario_name: str,
                          recipe_name: Optional[str] = None) -> KnowledgeGraph:
    """Deterministic build from a validated scenario config."""
    kg = KnowledgeGraph()

    enterprise = config.get("enterprise", "Enterprise")
    site = config.get("site", "Site")
    area = config.get("area", "Area")
    line = config.get("line_name", "Line1")
    comms = config.get("comms", {}) or {}
    spb_cfg = comms.get("sparkplugb", {}) or {}
    group_id = spb_cfg.get("group_id", area)
    edge_node_id = spb_cfg.get("edge_node_id", line)

    opcua_prefix = f"{enterprise}.{site}.{area}.{line}_Equipment"

    def opcua_nid(path: str) -> str:
        return f"ns=2;s={path}"

    def metric_addresses(station: str, metric: str, opcua_path: str,
                         rest_path: str) -> dict:
        return {
            "opcua_node_id": opcua_nid(opcua_path),
            "sparkplug_metric": {"group": group_id, "edge_node": edge_node_id,
                                 "device": station, "metric": metric},
            "mqtt_flat_topic": flat_topic(line, station, metric),
            "rest_path": rest_path,
        }

    # ----- ISA-95 hierarchy -----
    ent_id = f"enterprise:{enterprise}"
    site_id = f"site:{site}"
    area_id = f"area:{area}"
    line_id = f"line:{line}"
    kg.add_node(ent_id, "Enterprise", name=enterprise)
    kg.add_node(site_id, "Site", name=site)
    kg.add_node(area_id, "Area", name=area)
    kg.add_node(line_id, "Line", name=line,
                opcua_node_id=opcua_nid(opcua_prefix))
    kg.add_edge(ent_id, site_id, "CONTAINS")
    kg.add_edge(site_id, area_id, "CONTAINS")
    kg.add_edge(area_id, line_id, "CONTAINS")

    scenario_id = f"scenario:{scenario_name}"
    kg.add_node(scenario_id, "Scenario", name=scenario_name,
                description=config.get("description", ""))
    kg.add_edge(line_id, scenario_id, "RUNS")
    if recipe_name:
        recipe_id = f"recipe:{recipe_name}"
        kg.add_node(recipe_id, "Recipe", name=recipe_name)
        kg.add_edge(line_id, recipe_id, "RUNS")

    # ----- stations, buffers, material flow -----
    stations = config["stations"]
    buffers = config["buffers"]
    prev_id = None
    for i, st_cfg in enumerate(stations):
        st_name = st_cfg["name"]
        st_id = f"station:{st_name}"
        kg.add_node(
            st_id, "Station", name=st_name,
            cycle_time=st_cfg.get("cycle_time"),
            target_ppm=st_cfg.get("target_ppm"),
            defect_rate=st_cfg.get("defect_rate", 0.0),
            opcua_node_id=opcua_nid(
                f"{opcua_prefix}.Resources.{st_name}_Equipment"),
        )
        kg.add_edge(line_id, st_id, "CONTAINS")

        if prev_id is not None:
            b_cfg = buffers[i - 1]
            b_name = b_cfg["name"]
            b_id = f"buffer:{b_name}"
            kg.add_node(
                b_id, "Buffer", name=b_name, capacity=b_cfg["capacity"],
                opcua_node_id=opcua_nid(
                    f"{opcua_prefix}.Resources.{b_name}_StorageUnit"),
            )
            kg.add_edge(line_id, b_id, "CONTAINS")
            kg.add_edge(prev_id, b_id, "FEEDS")
            kg.add_edge(b_id, st_id, "FEEDS")
        prev_id = st_id

        # --- process values with full protocol address binding ---
        spc_enabled = bool(st_cfg.get("spc", {}).get("enabled", False))
        for pv_cfg in st_cfg.get("process_values", []):
            pv_name = pv_cfg["name"]
            pv_id = f"pv:{st_name}.{pv_name}"
            alarm_codes = []
            if "alarm_high" in pv_cfg:
                alarm_codes.append(alarm_defs.pv_code(pv_name, "HIGH"))
            if "alarm_low" in pv_cfg:
                alarm_codes.append(alarm_defs.pv_code(pv_name, "LOW"))
            kg.add_node(
                pv_id, "ProcessValue", name=pv_name, station=st_name,
                unit=pv_cfg["unit"], profile=pv_cfg["profile"],
                alarm_high=pv_cfg.get("alarm_high"),
                alarm_low=pv_cfg.get("alarm_low"),
                addresses=metric_addresses(
                    st_name, f"PV/{pv_name}",
                    f"{opcua_prefix}.Resources.{st_name}_Equipment"
                    f".ProcessValues.{pv_name}",
                    f"stations.{st_name}.process_values[name={pv_name}].value",
                ),
                alarm_codes=alarm_codes,
            )
            kg.add_edge(st_id, pv_id, "HAS_PV")
            for code in alarm_codes:
                code_id = _ensure_alarm_code(kg, code, "HIGH")
                kg.add_edge(st_id, code_id, "CAN_RAISE")
            if spc_enabled:
                spc_id = f"spc:{st_name}.{pv_name}"
                kg.add_node(spc_id, "Metric", name=f"SPC({pv_name})",
                            station=st_name, kind="spc_monitor")
                kg.add_edge(pv_id, spc_id, "MEASURED_BY")

        # --- failure modes ---
        for fm_cfg in st_cfg.get("failure_modes", []):
            fm_name = fm_cfg["name"]
            fm_id = f"fm:{st_name}.{fm_name}"
            code = alarm_defs.fm_code(fm_name)
            kg.add_node(fm_id, "FailureMode", name=fm_name, station=st_name,
                        failure_type=fm_cfg["type"], alarm_code=code)
            kg.add_edge(st_id, fm_id, "HAS_FAILURE_MODE")
            code_id = _ensure_alarm_code(kg, code, "CRITICAL")
            kg.add_edge(st_id, code_id, "CAN_RAISE")

        # --- cycle stops ---
        for cs_cfg in st_cfg.get("cycle_stops", []):
            reason = cs_cfg["reason"]
            code = alarm_defs.cs_code(reason)
            cs_id = f"cs:{st_name}.{code}"
            kg.add_node(cs_id, "CycleStopReason", name=reason, station=st_name,
                        alarm_code=code)
            code_id = _ensure_alarm_code(kg, code, "WARNING")
            kg.add_edge(st_id, code_id, "CAN_RAISE")

        # --- maintenance alarm (any station with a health model can repair) ---
        if "health" in st_cfg:
            code_id = _ensure_alarm_code(kg, alarm_defs.MT_REPAIR, "INFO")
            kg.add_edge(st_id, code_id, "CAN_RAISE")

        # --- published station metrics with full addresses ---
        for metric in STATION_METRIC_NAMES:
            metric_id = f"metric:{st_name}.{metric}"
            opcua_paths = {
                "State": "OperationsState.State",
                "Health": "OperationsState.HealthState",
                "PartsMade": "OperationsPerformance.PartCount",
                "Good": "OEE.GoodPartCount",
                "Scrap": "OperationsPerformance.ScrapCount",
                "OEE": "OEE.OEE",
                "Availability": "OEE.Availability",
                "Performance": "OEE.Performance",
                "Quality": "OEE.Quality",
                "ActiveReasonCode": "Alarms.ActiveReasonCode",
            }
            rest_fields = {
                "State": "state", "Health": "health", "PartsMade": "parts_made",
                "Good": "good", "Scrap": "scrap", "OEE": "oee",
                "Availability": "availability", "Performance": "performance",
                "Quality": "quality", "ActiveReasonCode": "alarms",
            }
            kg.add_node(
                metric_id, "Metric", name=metric, station=st_name,
                addresses=metric_addresses(
                    st_name, metric,
                    f"{opcua_prefix}.Resources.{st_name}_Equipment"
                    f".{opcua_paths[metric]}",
                    f"stations.{st_name}.{rest_fields[metric]}",
                ),
            )

    return kg


def _ensure_alarm_code(kg: KnowledgeGraph, code: str, severity: str) -> str:
    code_id = f"alarm:{code}"
    if code_id not in kg.nodes:
        kg.add_node(code_id, "AlarmCode", name=code, severity=severity)
    return code_id
