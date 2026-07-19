"""Gate P7.3 — BYO-key chat: SSE event shapes, key never persisted, degrade paths."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from simengine.api.rest import create_app
from simengine.runtime.run_manager import RunManager

PROJECT_CONFIG = Path(__file__).parents[1] / "config"
SECRET_KEY = "sk-ant-TESTSECRET-do-not-persist-12345"


@pytest.fixture
def chat_client(tmp_path, monkeypatch):
    scenarios = tmp_path / "config" / "scenarios.yaml"
    scenarios.parent.mkdir()
    shutil.copy(PROJECT_CONFIG / "scenarios.yaml", scenarios)
    (tmp_path / "results").mkdir()
    monkeypatch.setenv("SIMENGINE_CONFIG_PATH", str(scenarios))
    monkeypatch.setenv("SIMENGINE_RECIPE_PATH",
                       str(PROJECT_CONFIG / "recipes"))

    run_manager = RunManager()
    # give the registry a live-ish KG for the system prompt
    import yaml
    from simengine.engine.knowledge_graph import build_knowledge_graph
    config = yaml.safe_load(open(scenarios))["demo_line"]
    run_manager.knowledge_graph = build_knowledge_graph(config, "demo_line")

    app = create_app(run_manager)
    app.config["TESTING"] = True
    yield app.test_client(), tmp_path


def make_fake_runner():
    """One assistant turn: text + tool_use, then a tool_result, then done."""
    text_block = SimpleNamespace(type="text", text="Oil temp is 54.7 degC.")
    tool_block = SimpleNamespace(type="tool_use", name="resolve_metric",
                                 input={"query": "oil temperature"},
                                 id="toolu_1")
    response = SimpleNamespace(content=[text_block, tool_block],
                               stop_reason="tool_use")

    runner = MagicMock()
    runner.__iter__ = MagicMock(return_value=iter([response]))
    runner.generate_tool_call_response.return_value = {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                     "content": json.dumps({"value": 54.7})}],
    }
    return runner


def parse_sse(data: bytes):
    events = []
    for chunk in data.decode().split("\n\n"):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    return events


class TestChatTurn:
    def test_sse_event_shapes(self, chat_client):
        client, _ = chat_client
        fake_client = MagicMock()
        fake_client.beta.messages.tool_runner.return_value = make_fake_runner()
        with patch("anthropic.Anthropic", return_value=fake_client):
            r = client.post("/api/v1/chat", json={
                "message": "what's the oil temperature on Press01?",
                "api_key": SECRET_KEY,
            })
        assert r.status_code == 200
        assert r.mimetype == "text/event-stream"
        events = parse_sse(r.data)
        types = [e["type"] for e in events]
        assert "text" in types
        assert "tool_use" in types
        assert "tool_result" in types
        assert types[-1] == "done"
        tool_use = next(e for e in events if e["type"] == "tool_use")
        assert tool_use["name"] == "resolve_metric"

    def test_system_prompt_from_kg(self, chat_client):
        client, _ = chat_client
        fake_client = MagicMock()
        fake_client.beta.messages.tool_runner.return_value = make_fake_runner()
        with patch("anthropic.Anthropic", return_value=fake_client):
            client.post("/api/v1/chat", json={
                "message": "hi", "api_key": SECRET_KEY})
        kwargs = fake_client.beta.messages.tool_runner.call_args.kwargs
        system_text = kwargs["system"][0]["text"]
        assert "Press01" in system_text
        assert "OilTemp" in system_text
        assert "FM_BEARING_WEAR" in system_text
        assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert kwargs["model"] == "claude-opus-4-8"
        assert kwargs["thinking"] == {"type": "adaptive"}
        assert len(kwargs["tools"]) == 16

    def test_multi_turn_history_kept(self, chat_client):
        client, _ = chat_client
        fake_client = MagicMock()
        fake_client.beta.messages.tool_runner.side_effect = [
            make_fake_runner(), make_fake_runner()]
        with patch("anthropic.Anthropic", return_value=fake_client):
            client.post("/api/v1/chat", json={"message": "first",
                                              "api_key": SECRET_KEY}).data
            client.post("/api/v1/chat", json={"message": "second"}).data
        second_call = fake_client.beta.messages.tool_runner.call_args.kwargs
        roles = [m["role"] for m in second_call["messages"]]
        assert roles[0] == "user"          # first turn
        assert roles[-1] == "user"         # second turn
        assert len(second_call["messages"]) >= 4  # user, assistant, tool, user


class TestKeyHandling:
    def test_key_never_persisted(self, chat_client, caplog, capsys):
        client, tmp_path = chat_client
        fake_client = MagicMock()
        fake_client.beta.messages.tool_runner.return_value = make_fake_runner()
        with patch("anthropic.Anthropic", return_value=fake_client):
            r = client.post("/api/v1/chat", json={
                "message": "check", "api_key": SECRET_KEY})
            assert r.status_code == 200
            r.data  # drain stream

        # key never lands under config/ or results/
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert SECRET_KEY not in path.read_text(errors="ignore"), path
        # nor in captured logs / output
        assert SECRET_KEY not in caplog.text
        captured = capsys.readouterr()
        assert SECRET_KEY not in captured.out
        assert SECRET_KEY not in captured.err

    def test_status_reports_bool_only(self, chat_client):
        client, _ = chat_client
        s0 = client.get("/api/v1/chat/status").get_json()
        assert s0["chat_key_set"] is False
        assert SECRET_KEY not in json.dumps(s0)

        fake_client = MagicMock()
        fake_client.beta.messages.tool_runner.return_value = make_fake_runner()
        with patch("anthropic.Anthropic", return_value=fake_client):
            client.post("/api/v1/chat", json={"message": "x",
                                              "api_key": SECRET_KEY})
        s1 = client.get("/api/v1/chat/status").get_json()
        assert s1["chat_key_set"] is True
        assert SECRET_KEY not in json.dumps(s1)

    def test_missing_key_400(self, chat_client):
        client, _ = chat_client
        r = client.post("/api/v1/chat", json={"message": "hello"})
        assert r.status_code == 400
        assert "key" in r.get_json()["error"]


class TestDegradePaths:
    def test_missing_sdk_501(self, chat_client):
        client, _ = chat_client
        with patch("simengine.api.chat._anthropic_available", return_value=False):
            r = client.post("/api/v1/chat", json={"message": "x",
                                                  "api_key": SECRET_KEY})
        assert r.status_code == 501
        assert "simengine[chat]" in r.get_json()["error"]

    def test_bad_model_400(self, chat_client):
        client, _ = chat_client
        r = client.post("/api/v1/chat", json={
            "message": "x", "api_key": SECRET_KEY, "model": "gpt-4"})
        assert r.status_code == 400

    def test_clear_history(self, chat_client):
        client, _ = chat_client
        r = client.delete("/api/v1/chat")
        assert r.get_json() == {"cleared": True}

    def test_auth_error_surfaced(self, chat_client):
        client, _ = chat_client
        import anthropic as anthropic_mod
        fake_client = MagicMock()
        fake_client.beta.messages.tool_runner.side_effect = (
            anthropic_mod.AuthenticationError(
                "bad key", response=MagicMock(status_code=401),
                body=None))
        with patch("anthropic.Anthropic", return_value=fake_client):
            r = client.post("/api/v1/chat", json={"message": "x",
                                                  "api_key": SECRET_KEY})
        events = parse_sse(r.data)
        assert events[-1]["type"] == "error"
        assert "API key" in events[-1]["error"]
