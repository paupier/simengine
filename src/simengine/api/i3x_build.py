"""i3X (CESMII) object/relationship graph projection over the KnowledgeGraph.

Pinned against i3X tag 1.0.0, commit 34b766442f6ef614d47fe905459a2ea8b91c6f8b
(cesmii/i3X) -- field names and response-wrapper shapes below are copied from
that commit's demo/server/models.py and demo/server/routers/utils.py, not
improvised. See docs/superpowers/specs/2026-07-28-i3x-interface-design.md.

Built once per run alongside KnowledgeGraph (mirrors build_knowledge_graph's
own build-once pattern) -- this is a wire-projection concern, like the OPC
UA/MQTT/SparkplugB projections in publishers/, so it stays out of engine/.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

I3X_NAMESPACE_URI = "http://simengine.local/i3x/"

# Reverse-relationship naming: i3X's RelationshipType.reverseOf requires every
# relationship to declare its inverse's elementId. KG edges are directional
# but the KG itself has no notion of a named inverse, so this repo defines
# one pair of synthetic reverse names per KG edge type.
_REVERSE_OF = {
    "CONTAINS": "CONTAINED_BY", "FEEDS": "FED_BY", "HAS_PV": "PV_OF",
    "HAS_FAILURE_MODE": "FAILURE_MODE_OF", "CAN_RAISE": "RAISED_BY",
    "MEASURED_BY": "MEASURES", "RUNS": "RUN_BY",
}

_HTTP_TITLES = {
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 500: "Internal Server Error", 501: "Not Implemented",
}


def utc_now_iso() -> str:
    """RFC 3339 UTC with a literal 'Z' suffix -- the i3X Implementation Guide
    forbids the '+00:00' offset form."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def make_vqt(value: Any, quality: str, timestamp: str) -> dict:
    return {"value": value, "quality": quality, "timestamp": timestamp}


def run_quality(run_manager) -> str:
    return "Good" if run_manager.state == "RUNNING" else "GoodNoData"


def success_response(result: Any) -> dict:
    return {"success": True, "result": result}


def error_response(detail: str, status: int = 500) -> dict:
    title = _HTTP_TITLES.get(status, "Error")
    return {"success": False, "responseDetail": {"title": title, "status": status, "detail": detail}}


def bulk_response(results: List[dict]) -> dict:
    overall_success = all(r.get("success", False) for r in results)
    return {"success": overall_success, "results": results}


def _parent_id(kg, node_id: str) -> Optional[str]:
    for e in kg.edges:
        if e["type"] == "CONTAINS" and e["target"] == node_id:
            return e["source"]
    return None


def _is_composition(kg, node_id: str) -> bool:
    return any(e["type"] == "HAS_PV" and e["source"] == node_id for e in kg.edges)


def _build_objects(kg) -> List[dict]:
    return [
        {
            "elementId": node_id,
            "displayName": node.get("name", node_id),
            "typeElementId": f"type:{node['type']}",
            "parentId": _parent_id(kg, node_id),
            "isComposition": _is_composition(kg, node_id),
        }
        for node_id, node in kg.nodes.items()
    ]


def _build_objecttypes(kg) -> List[dict]:
    node_types = sorted({n["type"] for n in kg.nodes.values()})
    return [
        {
            "elementId": f"type:{t}",
            "displayName": t,
            "namespaceUri": I3X_NAMESPACE_URI,
            "sourceTypeId": f"simengine.{t}",
            "schema": {"type": "object"},  # KG nodes carry heterogeneous attrs; no fixed schema to declare
        }
        for t in node_types
    ]


def _build_relationshiptypes(kg) -> List[dict]:
    edge_types = sorted({e["type"] for e in kg.edges})
    return [
        {
            "elementId": f"rel:{t}",
            "displayName": t,
            "namespaceUri": I3X_NAMESPACE_URI,
            "relationshipId": f"simengine.{t}",
            "reverseOf": f"rel:{_REVERSE_OF[t]}",
        }
        for t in edge_types
    ]


def _build_namespaces() -> List[dict]:
    return [
        {"uri": I3X_NAMESPACE_URI, "displayName": "simengine i3X"},
        {"uri": "http://simengine.local/opcua", "displayName": "simengine OPC UA"},
        {"uri": "http://simengine.local/sparkplugb", "displayName": "simengine SparkplugB"},
        {"uri": "http://simengine.local/mqtt", "displayName": "simengine MQTT (flat topics)"},
        {"uri": "http://simengine.local/rest", "displayName": "simengine REST"},
    ]


def build_i3x_objects(kg) -> Dict[str, List[dict]]:
    return {
        "objects": _build_objects(kg),
        "objecttypes": _build_objecttypes(kg),
        "relationshiptypes": _build_relationshiptypes(kg),
        "namespaces": _build_namespaces(),
    }
