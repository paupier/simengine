"""Shared snapshot -> metric mapping for the MQTT publishers.

Metric names are identical across the Part 14 JSON and SparkplugB encodings
(architecture §3.2): differentiation is transport/encoding, never the data
model. Per-station metric names are unprefixed here; the Part 14 payload
prefixes them with "{Station}." while SparkplugB scopes them by device id.

STATION_METRIC_SCHEMA / LINE_METRIC_SCHEMA are the single source of truth for
"what metrics exist, in what order, with what datatype" — station_metrics()/
line_metrics() zip them with live values; station_metric_schema()/
line_metric_schema() (config-only, no live station/snapshot object) derive
the same name/datatype pairs for schema export (api/schema.py).
"""
from typing import Dict, List, Tuple

# SparkplugB datatype names (mapped to proto enum values in sparkplugb.py)
INT32 = "Int32"
FLOAT = "Float"
STRING = "String"
BOOLEAN = "Boolean"

_SEVERITY_ORDER = {"CRITICAL": 3, "HIGH": 2, "WARNING": 1, "INFO": 0}

STATION_METRIC_SCHEMA: Tuple[Tuple[str, str], ...] = (
    ("State", STRING),
    ("Health", INT32),
    ("PartsMade", INT32),
    ("Good", INT32),
    ("Scrap", INT32),
    ("OEE", FLOAT),
    ("Availability", FLOAT),
    ("Performance", FLOAT),
    ("Quality", FLOAT),
    ("ActiveReasonCode", STRING),
)

LINE_METRIC_SCHEMA: Tuple[Tuple[str, str], ...] = (
    ("SimTime", FLOAT),
    ("LineState", STRING),
    ("Throughput", FLOAT),
    ("TotalWIP", INT32),
    ("TotalGood", INT32),
    ("TotalScrap", INT32),
    ("OEE", FLOAT),
)


def top_reason_code(station_snapshot) -> str:
    alarms = station_snapshot.alarms
    if not alarms:
        return ""
    top = max(alarms, key=lambda a: (_SEVERITY_ORDER.get(a.severity, -1),
                                     a.activated_at))
    return top.code


def station_metric_schema(pv_names: List[str]) -> List[Tuple[str, str]]:
    """Static (name, datatype) pairs for one station's metrics — config-only,
    no live station object needed. Order/names match station_metrics() exactly."""
    schema = list(STATION_METRIC_SCHEMA)
    for name in pv_names:
        schema.append((f"PV/{name}", FLOAT))
    return schema


def line_metric_schema(buffer_names: List[str]) -> List[Tuple[str, str]]:
    """Static (name, datatype) pairs for line-level metrics — config-only.
    Order/names match line_metrics() exactly."""
    schema = list(LINE_METRIC_SCHEMA)
    for name in buffer_names:
        schema.append((f"Buffer/{name}/Level", INT32))
    return schema


def station_metrics(st) -> Dict[str, Tuple[object, str]]:
    """Ordered metric map for one station: name -> (value, datatype)."""
    values = {
        "State": st.state,
        "Health": st.health,
        "PartsMade": st.parts_made,
        "Good": st.good,
        "Scrap": st.scrap,
        "OEE": st.oee,
        "Availability": st.availability,
        "Performance": st.performance,
        "Quality": st.quality,
        "ActiveReasonCode": top_reason_code(st),
    }
    metrics = {name: (values[name], dtype) for name, dtype in STATION_METRIC_SCHEMA}
    for pv in st.process_values:
        metrics[f"PV/{pv.name}"] = (pv.value, FLOAT)
    return metrics


def line_metrics(snapshot) -> Dict[str, Tuple[object, str]]:
    """Ordered metric map for line-level (edge node) data."""
    values = {
        "SimTime": snapshot.sim_time,
        "LineState": snapshot.line_state,
        "Throughput": snapshot.throughput,
        "TotalWIP": snapshot.total_wip,
        "TotalGood": snapshot.total_good,
        "TotalScrap": snapshot.total_scrap,
        "OEE": snapshot.oee,
    }
    metrics = {name: (values[name], dtype) for name, dtype in LINE_METRIC_SCHEMA}
    for bname, buf in snapshot.buffers.items():
        metrics[f"Buffer/{bname}/Level"] = (buf.level, INT32)
    return metrics
