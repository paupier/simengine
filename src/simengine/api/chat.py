"""BYO-key Anthropic chat (AI interface spec §3).

Anthropic-only by design; other LLM stacks reach the system through the MCP
endpoint. The agent loop is the SDK tool runner over the same ToolRegistry
the MCP server exposes — called as direct function references, no MCP
round-trip.

Key handling (hard requirements):
- the API key lives only in process memory, keyed to the UI session;
- it is never written to disk, config files, YAML, logs, or the historian;
- GET endpoints never echo it — status reports only {"chat_key_set": bool}.

The `anthropic` SDK is an optional extra (pip install simengine[chat]);
endpoints degrade with an install hint when it is missing.
"""
import json
import logging
import uuid
from typing import Dict, Optional

from flask import Blueprint, Response, jsonify, request, session

from simengine.api.tools import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"
ALLOWED_MODELS = ("claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5")
MAX_TOKENS = 16000


def _anthropic_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("anthropic") is not None


class ChatState:
    """Per-UI-session chat state. The key never leaves process memory."""

    def __init__(self):
        self.api_key: Optional[str] = None
        self.model: str = DEFAULT_MODEL
        self.history: list = []


_sessions: Dict[str, ChatState] = {}


def _state() -> ChatState:
    sid = session.get("chat_sid")
    if sid is None:
        sid = uuid.uuid4().hex
        session["chat_sid"] = sid
    return _sessions.setdefault(sid, ChatState())


def build_system_prompt(kg) -> str:
    """Stable cached prefix assembled from the knowledge graph:
    topology summary (FEEDS chain), stations with cycle times, PVs with
    units/limits, and the alarm catalog. Per-turn state goes through tools."""
    lines = [
        "You are the operations assistant for a simengine production-line "
        "simulation. You can observe and control the live run through your "
        "tools; use them for any current value rather than guessing.",
        "",
    ]
    if kg is None:
        lines.append("No run is active yet; the knowledge graph is built at "
                     "run start. You can list scenarios and start a run.")
        return "\n".join(lines)

    line_nodes = kg.find_nodes("Line")
    line_name = line_nodes[0]["name"] if line_nodes else "Line"
    stations = kg.find_nodes("Station")
    feeds = kg.find_edges("FEEDS")
    chain = " -> ".join(
        ["Source"] + [e["source"].split(":", 1)[1] for e in feeds
                      if e["source"].startswith("station:")]
        + [feeds[-1]["target"].split(":", 1)[1] if feeds else ""]
        + ["Sink"]) if feeds else " -> ".join(
        ["Source"] + [s["name"] for s in stations] + ["Sink"])

    lines.append(f"## Line {line_name} topology")
    lines.append(f"Material flow: {chain}")
    lines.append("")
    lines.append("## Stations")
    for st in stations:
        ct = st.get("cycle_time")
        lines.append(f"- {st['name']}: cycle_time={ct}s, "
                     f"defect_rate={st.get('defect_rate', 0.0)}")
        for pv in kg.find_nodes("ProcessValue", station=st["name"]):
            limits = []
            if pv.get("alarm_high") is not None:
                limits.append(f"high={pv['alarm_high']}")
            if pv.get("alarm_low") is not None:
                limits.append(f"low={pv['alarm_low']}")
            lines.append(f"    - PV {pv['name']} [{pv['unit']}] "
                         f"profile={pv['profile']}"
                         + (f" alarm {' '.join(limits)}" if limits else ""))
    lines.append("")
    lines.append("## Alarm catalog")
    for code in kg.find_nodes("AlarmCode"):
        raised_by = [n["name"] for n in kg.neighbors(code["id"], "CAN_RAISE")]
        lines.append(f"- {code['name']} ({code['severity']}) — "
                     f"raised by: {', '.join(raised_by) or 'n/a'}")
    return "\n".join(lines)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def create_chat_blueprint(registry: ToolRegistry) -> Blueprint:
    chat = Blueprint("chat", __name__)

    @chat.get("/api/v1/chat/status")
    def chat_status():
        state = _state()
        return jsonify({
            "available": _anthropic_available(),
            "chat_key_set": state.api_key is not None,
            "model": state.model,
            "models": list(ALLOWED_MODELS),
        })

    @chat.delete("/api/v1/chat")
    def clear_chat():
        state = _state()
        state.history = []
        return jsonify({"cleared": True})

    @chat.post("/api/v1/chat")
    def chat_turn():
        if not _anthropic_available():
            return jsonify({"error": (
                "chat requires the anthropic SDK: pip install simengine[chat]"
            )}), 501

        body = request.get_json(force=True, silent=True) or {}
        message = body.get("message")
        if not message:
            return jsonify({"error": "message required"}), 400

        state = _state()
        if body.get("api_key"):
            state.api_key = body["api_key"]
        if body.get("model"):
            if body["model"] not in ALLOWED_MODELS:
                return jsonify({"error": f"model must be one of {ALLOWED_MODELS}"}), 400
            state.model = body["model"]
        if state.api_key is None:
            return jsonify({"error": "no API key set — enter your Anthropic key"}), 400

        return Response(
            _run_turn(registry, state, message),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return chat


def _build_tools(registry: ToolRegistry):
    from anthropic import beta_tool
    return [beta_tool(func) for _, func in registry.all_tools()]


def _run_turn(registry: ToolRegistry, state: ChatState, message: str):
    """Generator yielding SSE events for one chat turn (tool_runner loop)."""
    import anthropic

    client = anthropic.Anthropic(api_key=state.api_key)
    kg = registry.run_manager.knowledge_graph
    system = [{
        "type": "text",
        "text": build_system_prompt(kg),
        "cache_control": {"type": "ephemeral"},
    }]

    state.history.append({"role": "user", "content": message})
    try:
        runner = client.beta.messages.tool_runner(
            model=state.model,
            max_tokens=MAX_TOKENS,
            system=system,
            thinking={"type": "adaptive"},
            tools=_build_tools(registry),
            messages=list(state.history),
        )
        for response in runner:
            state.history.append(
                {"role": "assistant", "content": response.content})
            for block in response.content:
                if block.type == "text" and block.text:
                    yield _sse({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    yield _sse({"type": "tool_use", "name": block.name,
                                "input": block.input})
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                state.history.append(tool_response)
                for result in tool_response["content"]:
                    content = result.get("content")
                    yield _sse({
                        "type": "tool_result",
                        "tool_use_id": result.get("tool_use_id"),
                        "is_error": bool(result.get("is_error")),
                        "content": content if isinstance(content, (str, int, float))
                        else json.dumps(content, default=str)[:2000],
                    })
            if response.stop_reason == "refusal":
                yield _sse({"type": "text",
                            "text": "The model declined this request."})
        yield _sse({"type": "done"})
    except anthropic.AuthenticationError:
        state.history.pop()
        yield _sse({"type": "error", "error": "authentication failed — check your API key"})
    except anthropic.RateLimitError as e:
        state.history.pop()
        retry_after = e.response.headers.get("retry-after", "unknown")
        yield _sse({"type": "error",
                    "error": f"rate limited — retry after {retry_after}s"})
    except anthropic.APIStatusError as e:
        state.history.pop()
        yield _sse({"type": "error", "error": f"API error {e.status_code}"})
    except anthropic.APIConnectionError:
        state.history.pop()
        yield _sse({"type": "error", "error": "network error reaching the Anthropic API"})
