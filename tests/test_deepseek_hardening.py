"""
Guard-rail tests for Change 2: DeepSeek anti-hallucination hardening.

Verifies that the /api/voice/chat endpoint passes deterministic parameters
(temperature=0.1, response_format=json_object) and appends the CRITICAL
RULES block to the DeepSeek system prompt.

All tests mock both DeepSeek and Qwen clients so no external API calls occur.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """TestClient with Telegram bot thread mocked off."""
    import init_db
    init_db.init_database()
    import migrate_database
    try:
        migrate_database.migrate_database()
    except Exception:
        pass
    import migrate_add_tables
    try:
        migrate_add_tables.migrate()
    except Exception:
        pass

    with patch("main.Thread") as mock_thread, \
         patch("main.requests") as mock_req:
        mock_thread.return_value.start.return_value = None
        mock_req.post.return_value = MagicMock(text='{"ok": true}', json=lambda: {"ok": True})

        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _build_ds_response(payload):
    """Wrap a JSON payload in the OpenAI-SDK response envelope."""
    msg = MagicMock()
    msg.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _build_qwen_response(payload):
    msg = MagicMock()
    msg.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _invoke_voice_chat(client, speech="satu teh tarik"):
    """POST to /api/voice/chat with mocked DeepSeek + Qwen clients.

    Returns the mocked DeepSeek client so tests can inspect call_args.
    """
    mock_ds = MagicMock()
    mock_ds.chat.completions.create.return_value = _build_ds_response(
        {"items": [{"matched_item": "teh tarik", "quantity": 1,
                    "confidence": 0.95, "modifiers": []}]}
    )

    mock_qwen = MagicMock()
    mock_qwen.chat.completions.create.return_value = _build_qwen_response(
        {"items": ["teh tarik"], "quantities": [1],
         "action": "add", "reply": "Baiklah."}
    )

    with patch("main.get_deepseek_client", return_value=mock_ds), \
         patch("main.get_qwen_client", return_value=mock_qwen):
        resp = client.post("/api/voice/chat", json={
            "message": speech,
            "alternatives": [],
            "order": [],
            "table_number": "T01",
        })
    assert resp.status_code == 200, resp.text
    return mock_ds


def test_temperature_is_low(client):
    mock_ds = _invoke_voice_chat(client)
    assert mock_ds.chat.completions.create.called, "DeepSeek was not called"
    kwargs = mock_ds.chat.completions.create.call_args.kwargs
    assert kwargs.get("temperature") == 0.1, \
        f"temperature must be 0.1, got {kwargs.get('temperature')!r}"


def test_response_format_json(client):
    mock_ds = _invoke_voice_chat(client)
    kwargs = mock_ds.chat.completions.create.call_args.kwargs
    assert kwargs.get("response_format") == {"type": "json_object"}, \
        f"response_format must force json_object, got {kwargs.get('response_format')!r}"


def test_critical_rules_in_prompt(client):
    mock_ds = _invoke_voice_chat(client)
    kwargs = mock_ds.chat.completions.create.call_args.kwargs
    messages = kwargs.get("messages", [])
    assert messages, "no messages passed to DeepSeek"
    system_content = messages[0].get("content", "")
    assert "CRITICAL RULES" in system_content, \
        "CRITICAL RULES block missing from DeepSeek system prompt"
