"""i3X (CESMII) REST interface -- read + subscriptions, no writes.

Positioned as a test/reference data source for i3X tooling, not a production
path Optix will consume. See docs/superpowers/specs/2026-07-28-i3x-interface-
design.md. Pinned against i3X tag 1.0.0.
"""
import json
import threading
import time as _time

from flask import Blueprint, Response, jsonify, request

from simengine.api.i3x_build import (
    build_i3x_objects, error_response, make_vqt, run_quality, success_response,
    utc_now_iso,
)
from simengine.api.i3x_subscriptions import SubscriptionRegistry

I3X_SPEC_VERSION = "1.0"

_subscriptions = SubscriptionRegistry()


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _start_poll_worker(run_manager):
    """Background daemon: every 0.2s, if a new snapshot has arrived, stage a
    fresh VQT for every element id currently monitored by any subscription."""
    last_step_count = {"value": None}

    def _poll():
        while True:
            _time.sleep(0.2)
            snap = run_manager.latest_snapshot
            if snap is None or snap.step_count == last_step_count["value"]:
                continue
            last_step_count["value"] = snap.step_count
            graph = _current_graph(run_manager)
            if graph is None:
                continue
            timestamp = utc_now_iso()
            quality = run_quality(run_manager)
            monitored_ids = _subscriptions.all_monitored_element_ids()
            for eid in monitored_ids:
                value = _resolve_value(snap, eid)
                _subscriptions.stage_update(eid, value, quality if value is not None else "GoodNoData", timestamp)

    thread = threading.Thread(target=_poll, daemon=True, name="i3x-subscription-poller")
    thread.start()

# {node_type: metric-name -> snapshot field name}, copied from the exact maps
# already used to build each Metric node's REST address in
# engine/knowledge_graph.py::build_knowledge_graph -- do not re-derive these.
_METRIC_REST_FIELDS = {
    "State": "state", "Health": "health", "PartsMade": "parts_made",
    "Good": "good", "Scrap": "scrap", "OEE": "oee",
    "Availability": "availability", "Performance": "performance",
    "Quality": "quality", "ActiveReasonCode": "alarms",
}


def _resolve_value(snap, element_id: str):
    """Live value for a Metric or ProcessValue node id; None for anything else
    (structural nodes have no directly associated live value).

    Takes an already-captured LineSnapshot rather than run_manager, so every
    caller resolves a whole batch of element ids against exactly one
    snapshot -- avoiding a bulk request tearing across an engine step
    boundary if it instead re-read run_manager.latest_snapshot per element."""
    if snap is None:
        return None

    if element_id.startswith("metric:"):
        station_name, metric = element_id[len("metric:"):].split(".", 1)
        field = _METRIC_REST_FIELDS.get(metric)
        if field is None:
            return None
        station = snap.stations.get(station_name)
        if station is None:
            return None
        if field == "alarms":
            alarms = station.alarms
            return alarms[0].code if alarms else None
        return getattr(station, field, None)

    if element_id.startswith("pv:"):
        station_name, pv_name = element_id[len("pv:"):].split(".", 1)
        station = snap.stations.get(station_name)
        if station is None:
            return None
        pv = next((p for p in station.process_values if p.name == pv_name), None)
        return pv.value if pv else None

    return None

# Cache of the last-built object graph, keyed by id(run_manager.knowledge_graph)
# -- rebuilt only when the active run changes, mirroring how
# run_manager.knowledge_graph itself is "built at run start, static per run."
#
# Keyed on object identity rather than run_manager.run_id: run_id is
# f"{scenario}_{datetime.now().strftime('%Y%m%d_%H%M%S')}" (1-second
# resolution), so stopping and restarting the same scenario within the same
# wall-clock second produces an identical run_id string and would leave this
# cache serving the previous run's stale graph. A fresh KnowledgeGraph
# instance is built on every start() (run_manager.py), so id() is
# collision-proof where the timestamp string isn't.
_graph_cache = {"run_id": None, "graph": None}


def _current_graph(run_manager):
    if run_manager.knowledge_graph is None:
        return None
    cache_key = id(run_manager.knowledge_graph)
    if _graph_cache["run_id"] != cache_key:
        _graph_cache["run_id"] = cache_key
        _graph_cache["graph"] = build_i3x_objects(run_manager.knowledge_graph)
    return _graph_cache["graph"]


def _i3x_enabled(run_manager) -> bool:
    if not run_manager.config:
        return False
    return bool(run_manager.config.get("comms", {}).get("i3x", {}).get("enabled", False))


def create_i3x_blueprint(run_manager) -> Blueprint:
    i3x = Blueprint("i3x", __name__, url_prefix="/i3x/v1")

    @i3x.before_request
    def _gate():
        # Flask's blueprint-qualified endpoint name ("i3x.get_info"), not the
        # URL path -- stays correct if the blueprint's url_prefix ever changes.
        if request.endpoint == "i3x.get_info":
            return None
        if not _i3x_enabled(run_manager):
            return jsonify(error_response(
                "i3X is not enabled for the active scenario (comms.i3x.enabled=false, or no run active)",
                403,
            )), 403
        return None

    @i3x.get("/info")
    def get_info():
        return jsonify(success_response({
            "specVersion": I3X_SPEC_VERSION,
            "serverVersion": None,
            "serverName": "simengine",
            "capabilities": {
                "query": {"history": True},
                "update": {"current": False, "history": False},
                "subscribe": {"stream": True},
            },
        }))

    @i3x.get("/namespaces")
    def get_namespaces():
        graph = _current_graph(run_manager)
        return jsonify(success_response(graph["namespaces"]))

    @i3x.get("/objecttypes")
    def get_objecttypes():
        graph = _current_graph(run_manager)
        return jsonify(success_response(graph["objecttypes"]))

    @i3x.post("/objecttypes/query")
    def query_objecttypes():
        graph = _current_graph(run_manager)
        by_id = {t["elementId"]: t for t in graph["objecttypes"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        for eid in body.get("elementIds", []):
            if eid in by_id:
                results.append({"success": True, "elementId": eid, "result": by_id[eid]})
            else:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Object type not found: {eid}"}})
        overall = all(r["success"] for r in results)
        return jsonify({"success": overall, "results": results})

    @i3x.get("/relationshiptypes")
    def get_relationshiptypes():
        graph = _current_graph(run_manager)
        return jsonify(success_response(graph["relationshiptypes"]))

    @i3x.post("/relationshiptypes/query")
    def query_relationshiptypes():
        graph = _current_graph(run_manager)
        by_id = {t["elementId"]: t for t in graph["relationshiptypes"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        for eid in body.get("elementIds", []):
            if eid in by_id:
                results.append({"success": True, "elementId": eid, "result": by_id[eid]})
            else:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Relationship type not found: {eid}"}})
        overall = all(r["success"] for r in results)
        return jsonify({"success": overall, "results": results})

    @i3x.get("/objects")
    def get_objects():
        graph = _current_graph(run_manager)
        return jsonify(success_response(graph["objects"]))

    @i3x.post("/objects/list")
    def list_objects():
        graph = _current_graph(run_manager)
        by_id = {o["elementId"]: o for o in graph["objects"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        for eid in body.get("elementIds", []):
            if eid in by_id:
                results.append({"success": True, "elementId": eid, "result": by_id[eid]})
            else:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Element not found: {eid}"}})
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/objects/related")
    def objects_related():
        kg = run_manager.knowledge_graph
        graph = _current_graph(run_manager)
        by_id = {o["elementId"]: o for o in graph["objects"]}
        body = request.get_json(force=True, silent=True) or {}
        results = []
        relationship_type_filter = body.get("relationshipType")
        for eid in body.get("elementIds", []):
            if eid not in by_id:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Element not found: {eid}"}})
                continue
            related = []
            for edge in kg.edges:
                edge_rel_type = f"rel:{edge['type']}"
                # Skip if filter is set and this edge doesn't match
                if relationship_type_filter is not None and edge_rel_type != relationship_type_filter:
                    continue
                if edge["source"] == eid:
                    related.append({"sourceRelationship": edge_rel_type, "object": by_id[edge["target"]]})
                elif edge["target"] == eid:
                    related.append({"sourceRelationship": edge_rel_type, "object": by_id[edge["source"]]})
            results.append({"success": True, "elementId": eid, "result": related})
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/objects/value")
    def objects_value():
        graph = _current_graph(run_manager)
        by_id = {o["elementId"]: o for o in graph["objects"]}
        kg = run_manager.knowledge_graph
        body = request.get_json(force=True, silent=True) or {}
        # 0=infinite, 1(default)=no recursion. Composition nesting in this KG
        # is exactly one level deep (Station/Buffer -HAS_PV-> ProcessValue,
        # never deeper), so "0" and "2+" both just mean "include the direct
        # HAS_PV children" -- there's no third level to recurse into.
        max_depth = body.get("maxDepth", 1)
        snap = run_manager.latest_snapshot  # captured once for the whole request
        results = []
        for eid in body.get("elementIds", []):
            obj = by_id.get(eid)
            if obj is None:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Element not found: {eid}"}})
                continue
            value = _resolve_value(snap, eid)
            quality = run_quality(run_manager) if value is not None else "GoodNoData"
            timestamp = utc_now_iso()
            result = {
                "isComposition": obj["isComposition"],
                **make_vqt(value, quality, timestamp),
            }
            if obj["isComposition"] and max_depth != 1 and kg is not None:
                components = {}
                for edge in kg.edges:
                    if edge["type"] == "HAS_PV" and edge["source"] == eid:
                        child_id = edge["target"]
                        child_value = _resolve_value(snap, child_id)
                        child_quality = run_quality(run_manager) if child_value is not None else "GoodNoData"
                        components[child_id] = make_vqt(child_value, child_quality, timestamp)
                result["components"] = components
            results.append({"success": True, "elementId": eid, "result": result})
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/objects/history")
    def objects_history():
        graph = _current_graph(run_manager)
        by_id = {o["elementId"]: o for o in graph["objects"]}
        kg = run_manager.knowledge_graph
        body = request.get_json(force=True, silent=True) or {}
        max_depth = body.get("maxDepth", 1)
        results = []
        for eid in body.get("elementIds", []):
            obj = by_id.get(eid)
            if obj is None:
                results.append({"success": False, "elementId": eid,
                                "responseDetail": {"title": "Not Found", "status": 404,
                                                   "detail": f"Element not found: {eid}"}})
                continue
            # No in-process value history by design (see the SPC/Welford memory
            # note in CLAUDE.md) -- empty is the valid, spec-shaped answer, not
            # an error, unless a historian-influx backend is wired in later.
            result = {"isComposition": obj["isComposition"], "values": []}
            if obj["isComposition"] and max_depth != 1 and kg is not None:
                components = {}
                for edge in kg.edges:
                    if edge["type"] == "HAS_PV" and edge["source"] == eid:
                        components[edge["target"]] = {"values": []}
                result["components"] = components
            results.append({"success": True, "elementId": eid, "result": result})
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/subscriptions")
    def create_subscription():
        body = request.get_json(force=True, silent=True) or {}
        client_id = body.get("clientId")
        if not client_id:
            return jsonify(error_response("clientId is required", 400)), 400
        result = _subscriptions.create(client_id, body.get("displayName"))
        return jsonify(success_response(result))

    @i3x.post("/subscriptions/register")
    def register_subscription():
        body = request.get_json(force=True, silent=True) or {}
        client_id = body.get("clientId")
        if not client_id:
            return jsonify(error_response("clientId is required", 400)), 400
        subscription_id = body.get("subscriptionId")
        if not subscription_id:
            return jsonify(error_response("subscriptionId is required", 400)), 400
        max_depth = body.get("maxDepth", 1)
        graph = _current_graph(run_manager)
        by_id = {o["elementId"]: o for o in graph["objects"]}
        known_ids = set(by_id)
        kg = run_manager.knowledge_graph
        requested_ids = list(body.get("elementIds", []))
        element_ids = list(requested_ids)
        if kg is not None and max_depth != 1:
            for eid in requested_ids:
                obj = by_id.get(eid)
                if obj is not None and obj["isComposition"]:
                    for edge in kg.edges:
                        if edge["type"] == "HAS_PV" and edge["source"] == eid:
                            element_ids.append(edge["target"])
        results = _subscriptions.register(client_id, subscription_id,
                                          element_ids, known_ids)
        if results is None:
            return jsonify(error_response("Subscription not found", 404)), 404
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/subscriptions/unregister")
    def unregister_subscription():
        body = request.get_json(force=True, silent=True) or {}
        client_id = body.get("clientId")
        if not client_id:
            return jsonify(error_response("clientId is required", 400)), 400
        subscription_id = body.get("subscriptionId")
        if not subscription_id:
            return jsonify(error_response("subscriptionId is required", 400)), 400
        results = _subscriptions.unregister(client_id, subscription_id, body.get("elementIds", []))
        if results is None:
            return jsonify(error_response("Subscription not found", 404)), 404
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/subscriptions/delete")
    def delete_subscriptions():
        body = request.get_json(force=True, silent=True) or {}
        client_id = body.get("clientId")
        if not client_id:
            return jsonify(error_response("clientId is required", 400)), 400
        results = _subscriptions.delete(client_id, body.get("subscriptionIds", []))
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/subscriptions/list")
    def list_subscriptions():
        body = request.get_json(force=True, silent=True) or {}
        client_id = body.get("clientId")
        if not client_id:
            return jsonify(error_response("clientId is required", 400)), 400
        results = _subscriptions.list(client_id, body.get("subscriptionIds", []))
        return jsonify({"success": all(r["success"] for r in results), "results": results})

    @i3x.post("/subscriptions/sync")
    def sync_subscription():
        body = request.get_json(force=True, silent=True) or {}
        client_id = body.get("clientId")
        if not client_id:
            return jsonify(error_response("clientId is required", 400)), 400
        subscription_id = body.get("subscriptionId")
        if not subscription_id:
            return jsonify(error_response("subscriptionId is required", 400)), 400
        batches = _subscriptions.sync(client_id, subscription_id, body.get("lastSequenceNumber"))
        if batches is None:
            return jsonify(error_response("Subscription not found", 404)), 404
        return jsonify(success_response(batches))

    @i3x.post("/subscriptions/stream")
    def stream_subscription():
        body = request.get_json(force=True, silent=True) or {}
        client_id = body.get("clientId")
        if not client_id:
            return jsonify(error_response("clientId is required", 400)), 400
        subscription_id = body.get("subscriptionId")
        if not subscription_id:
            return jsonify(error_response("subscriptionId is required", 400)), 400
        if _subscriptions.find(client_id, subscription_id) is None:
            return jsonify(error_response("Subscription not found", 404)), 404

        def _events():
            last_acked = None
            while True:
                batches = _subscriptions.sync(client_id, subscription_id, last_acked)
                if batches is None:
                    return  # subscription deleted mid-stream
                for batch in batches:
                    yield _sse(batch)
                    last_acked = batch["sequenceNumber"]
                _time.sleep(0.25)

        return Response(_events(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    _start_poll_worker(run_manager)

    return i3x
