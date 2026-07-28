"""i3X (CESMII) REST interface -- read + subscriptions, no writes.

Positioned as a test/reference data source for i3X tooling, not a production
path Optix will consume. See docs/superpowers/specs/2026-07-28-i3x-interface-
design.md. Pinned against i3X tag 1.0.0.
"""
from flask import Blueprint, jsonify, request

from simengine.api.i3x_build import build_i3x_objects, error_response, success_response

I3X_SPEC_VERSION = "1.0"

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
        if request.path == "/i3x/v1/info":
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

    return i3x
