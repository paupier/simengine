"""Shared snapshot -> metric mapping for the MQTT publishers.

Metric names are identical across the Part 14 JSON and SparkplugB encodings
(architecture §3.2): differentiation is transport/encoding, never the data
model. Per-station metric names are unprefixed here; the Part 14 payload
prefixes them with "{Station}." while SparkplugB scopes them by device id.
"""
from typing import Dict, Tuple

# SparkplugB datatype names (mapped to proto enum values in sparkplugb.py)
INT32 = "Int32"
FLOAT = "Float"
STRING = "String"
BOOLEAN = "Boolean"

_SEVERITY_ORDER = {"CRITICAL": 3, "HIGH": 2, "WARNING": 1, "INFO": 0}


def top_reason_code(station_snapshot) -> str:
    alarms = station_snapshot.alarms
    if not alarms:
        return ""
    top = max(alarms, key=lambda a: (_SEVERITY_ORDER.get(a.severity, -1),
                                     a.activated_at))
    return top.code


def station_metrics(st) -> Dict[str, Tuple[object, str]]:
    """Ordered metric map for one station: name -> (value, datatype)."""
    metrics = {
        "State": (st.state, STRING),
        "Health": (st.health, INT32),
        "PartsMade": (st.parts_made, INT32),
        "Good": (st.good, INT32),
        "Scrap": (st.scrap, INT32),
        "OEE": (st.oee, FLOAT),
        "Availability": (st.availability, FLOAT),
        "Performance": (st.performance, FLOAT),
        "Quality": (st.quality, FLOAT),
        "ActiveReasonCode": (top_reason_code(st), STRING),
    }
    for pv in st.process_values:
        metrics[f"PV/{pv.name}"] = (pv.value, FLOAT)
    return metrics


def line_metrics(snapshot) -> Dict[str, Tuple[object, str]]:
    """Ordered metric map for line-level (edge node) data."""
    metrics = {
        "SimTime": (snapshot.sim_time, FLOAT),
        "LineState": (snapshot.line_state, STRING),
        "Throughput": (snapshot.throughput, FLOAT),
        "TotalWIP": (snapshot.total_wip, INT32),
        "TotalGood": (snapshot.total_good, INT32),
        "TotalScrap": (snapshot.total_scrap, INT32),
        "OEE": (snapshot.oee, FLOAT),
    }
    for bname, buf in snapshot.buffers.items():
        metrics[f"Buffer/{bname}/Level"] = (buf.level, INT32)
    return metrics
