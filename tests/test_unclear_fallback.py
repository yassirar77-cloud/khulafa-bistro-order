"""Tests for the unclear-order fallback to cashier + waiter (Change 4)."""
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import main


@pytest.fixture(autouse=True)
def reset_unclear_state():
    with main._unclear_lock:
        main._unclear_dedup_cache.clear()
        main._unclear_rate_table.clear()
        main._unclear_rate_global.clear()
        main._unclear_alerts_pending.clear()
        main._transcribe_audio_cache.clear()
    yield
    with main._unclear_lock:
        main._unclear_dedup_cache.clear()
        main._unclear_rate_table.clear()
        main._unclear_rate_global.clear()
        main._unclear_alerts_pending.clear()
        main._transcribe_audio_cache.clear()


UNCLEAR_DS = [{
    "matched_item": "",
    "quantity": 0,
    "confidence": 0,
    "modifiers": [],
    "needs_clarification": True,
    "heard_text": "mumble mumble",
}]

CLEAR_DS = [{
    "matched_item": "roti canai",
    "quantity": 1,
    "confidence": 0.95,
    "modifiers": [],
}]


def test_empty_text_no_alert():
    should, reason = main.should_trigger_unclear_fallback("T01", "", UNCLEAR_DS)
    assert should is False
    assert reason == "empty_text"


def test_single_word_no_alert():
    should, reason = main.should_trigger_unclear_fallback(
        "T01", "maggi", UNCLEAR_DS)
    assert should is False
    assert reason == "single_word"


def test_clear_match_no_alert():
    should, reason = main.should_trigger_unclear_fallback(
        "T01", "satu roti canai", CLEAR_DS)
    assert should is False
    assert reason == "clear_match"


def test_unclear_triggers_alert():
    should, reason = main.should_trigger_unclear_fallback(
        "T01", "something mumbled unclear", UNCLEAR_DS)
    assert should is True
    assert reason == "unclear"
    with main._unclear_lock:
        assert ("T01", "something mumbled unclear") in main._unclear_dedup_cache
        assert len(main._unclear_rate_table.get("T01", [])) == 1
        assert len(main._unclear_rate_global) == 1


def test_dedup_within_window():
    first, _ = main.should_trigger_unclear_fallback(
        "T01", "muffled request here", UNCLEAR_DS)
    assert first is True
    second, reason = main.should_trigger_unclear_fallback(
        "T01", "muffled request here", UNCLEAR_DS)
    assert second is False
    assert reason == "dedup"


def test_dedup_expires_after_window():
    first, _ = main.should_trigger_unclear_fallback(
        "T01", "muffled request here", UNCLEAR_DS)
    assert first is True
    # Rewind the dedup timestamp past the window to simulate >30s elapsed.
    key = ("T01", "muffled request here")
    with main._unclear_lock:
        main._unclear_dedup_cache[key] -= (main.UNCLEAR_DEDUP_WINDOW_SECONDS + 1)
    second, reason = main.should_trigger_unclear_fallback(
        "T01", "muffled request here", UNCLEAR_DS)
    assert second is True
    assert reason == "unclear"


def test_rate_limit_per_table():
    now = time.time()
    with main._unclear_lock:
        main._unclear_rate_table["T01"] = [
            now for _ in range(main.UNCLEAR_RATE_LIMIT_PER_TABLE_PER_MINUTE)]
    should, reason = main.should_trigger_unclear_fallback(
        "T01", "some unclear request text", UNCLEAR_DS)
    assert should is False
    assert reason == "rate_limit_table"


async def test_handled_button_updates_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("logs").mkdir()

    alert_id = "abc12345"
    with main._unclear_lock:
        main._unclear_alerts_pending[alert_id] = {
            "table": "T01",
            "text": "muffled request here",
            "created_at": time.time() - 8,
        }

    query = MagicMock()
    query.message.text = "⚠️ TABLE T01 NEEDS WAITER\n..."
    query.from_user.username = "waiter_ali"
    query.from_user.first_name = "Ali"
    query.edit_message_text = AsyncMock()

    await main._handle_unclear_callback(query, f"unclear_handled_{alert_id}")

    query.edit_message_text.assert_awaited_once()
    args, kwargs = query.edit_message_text.call_args
    new_text = kwargs.get("text") or (args[0] if args else "")
    assert "✅ RESOLVED" in new_text
    assert "@waiter_ali" in new_text

    log_file = tmp_path / "logs" / "unclear_resolved.jsonl"
    assert log_file.exists()
    entries = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    assert entries[0]["alert_id"] == alert_id
    assert entries[0]["resolver"] == "waiter_ali"
    assert entries[0]["table"] == "T01"

    with main._unclear_lock:
        assert alert_id not in main._unclear_alerts_pending
