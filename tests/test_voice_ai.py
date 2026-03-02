# tests/test_voice_ai.py
"""
P2 PRIORITY — Voice AI integration tests with mocked external calls.
Tests build_system_prompt, get_time_of_day, and chat_with_voice.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from voice_ai import build_system_prompt, get_time_of_day, get_greeting_with_audio


# ============================================================
# get_time_of_day
# ============================================================


class TestGetTimeOfDay:

    @pytest.mark.parametrize("hour,expected", [
        (5, "morning"), (6, "morning"), (10, "morning"), (11, "morning"),
        (12, "afternoon"), (13, "afternoon"), (14, "afternoon"),
        (15, "evening"), (17, "evening"), (18, "evening"),
        (19, "night"), (22, "night"), (0, "night"), (3, "night"),
    ])
    def test_time_classification(self, hour, expected):
        from datetime import datetime
        with patch("voice_ai.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, hour, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = get_time_of_day()
            assert result == expected


# ============================================================
# build_system_prompt
# ============================================================


class TestBuildSystemPrompt:

    def test_prompt_contains_table_number(self):
        prompt = build_system_prompt("T05", "teh tarik - RM3.50")
        assert "T05" in prompt

    def test_prompt_contains_menu_context(self):
        menu = "roti canai - RM2.00\nnaan butter garlic - RM4.50"
        prompt = build_system_prompt("T01", menu)
        assert "roti canai" in prompt
        assert "naan butter garlic" in prompt

    def test_prompt_not_empty(self):
        prompt = build_system_prompt("T01", "")
        assert len(prompt) > 50

    def test_prompt_contains_rules(self):
        prompt = build_system_prompt("T01", "menu")
        assert "JANGAN" in prompt or "Ada lagi" in prompt


# ============================================================
# chat_with_voice (async, mocked API)
# ============================================================


class TestChatWithVoice:

    @pytest.mark.asyncio
    async def test_returns_dict_with_required_keys(self):
        from voice_ai import chat_with_voice

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Roti canai satu. Ada lagi?"

        with patch("voice_ai.get_client") as mock_client, \
             patch("voice_ai.get_aisha") as mock_aisha:
            mock_client.return_value.chat.completions.create.return_value = mock_response
            mock_aisha_inst = MagicMock()
            mock_aisha_inst.find_matches_in_response.return_value = [
                {"id": "0052", "text": "Roti canai satu.", "score": 0.95, "audio_path": "/audio/wavs/0052.wav"}
            ]
            mock_aisha.return_value = mock_aisha_inst

            result = await chat_with_voice("roti canai satu", [], "T01", "roti canai - RM2.00")

            assert "text" in result
            assert "audio_matches" in result
            assert "has_audio" in result
            assert result["text"] == "Roti canai satu. Ada lagi?"
            assert result["has_audio"] is True

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self):
        from voice_ai import chat_with_voice

        with patch("voice_ai.get_client") as mock_client, \
             patch("voice_ai.get_aisha") as mock_aisha:
            mock_client.return_value.chat.completions.create.side_effect = Exception("API down")
            mock_aisha_inst = MagicMock()
            mock_aisha_inst.find_matches_in_response.return_value = []
            mock_aisha_inst.find_best_match.return_value = None
            mock_aisha.return_value = mock_aisha_inst

            result = await chat_with_voice("roti canai", [], "T01", "menu")

            # Should return fallback, not crash
            assert result is not None
            assert "text" in result

    @pytest.mark.asyncio
    async def test_empty_audio_matches_sets_has_audio_false(self):
        from voice_ai import chat_with_voice

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Some response."

        with patch("voice_ai.get_client") as mock_client, \
             patch("voice_ai.get_aisha") as mock_aisha:
            mock_client.return_value.chat.completions.create.return_value = mock_response
            mock_aisha_inst = MagicMock()
            mock_aisha_inst.find_matches_in_response.return_value = []
            mock_aisha_inst.find_best_match.return_value = None
            mock_aisha.return_value = mock_aisha_inst

            result = await chat_with_voice("random text", [], "T01", "menu")
            assert result["has_audio"] is False


# ============================================================
# get_greeting_with_audio
# ============================================================


class TestGetGreetingWithAudio:

    def test_returns_dict(self):
        with patch("voice_ai.get_aisha") as mock_aisha:
            mock_inst = MagicMock()
            mock_inst.get_greeting.return_value = {
                "id": "0005", "text": "Selamat pagi!", "score": 1.0,
                "audio_path": "/audio/wavs/0005.wav"
            }
            mock_aisha.return_value = mock_inst

            result = get_greeting_with_audio()
            assert "text" in result
            assert "audio_matches" in result
            assert "has_audio" in result

    def test_fallback_when_no_audio(self):
        with patch("voice_ai.get_aisha") as mock_aisha:
            mock_inst = MagicMock()
            mock_inst.get_greeting.return_value = None
            mock_aisha.return_value = mock_inst

            result = get_greeting_with_audio()
            assert result["has_audio"] is False
            assert "Khulafa Bistro" in result["text"]
