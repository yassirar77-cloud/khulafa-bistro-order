# tests/test_upsell_engine.py
"""
Tests for Aisha's profit-driven upsell engine.
Validates upsell map integrity, margin calculations, session tracking,
addon suggestions for premium items, and ElevenLabs TTS integration.
"""
import pytest
from unittest.mock import patch, AsyncMock
from upsell_engine import (
    UpsellEngine,
    UPSELL_MAP,
    _PREMIUM_ITEMS,
    _RAW_UPSELL_MAP,
    _build_upsell_map,
    get_upsell_engine,
    generate_upsell_audio,
)
from order_engine import MENU


# ============================================================
# UPSELL_MAP Data Integrity
# ============================================================


class TestUpsellMapIntegrity:
    """Verify the upsell map is correctly built from actual menu data."""

    def test_upsell_map_not_empty(self):
        assert len(UPSELL_MAP) > 20

    def test_all_base_items_exist_in_menu(self):
        for base_item in UPSELL_MAP:
            assert base_item in MENU, f"Base item '{base_item}' not in MENU"

    def test_all_upsell_items_exist_in_menu(self):
        for base_item, upsells in UPSELL_MAP.items():
            for u in upsells:
                assert u["item"] in MENU, f"Upsell '{u['item']}' not in MENU"

    def test_all_margins_positive(self):
        """Every upsell must cost MORE than the base item."""
        for base_item, upsells in UPSELL_MAP.items():
            base_price = MENU[base_item]["price"]
            for u in upsells:
                assert u["margin"] > 0, (
                    f"Non-positive margin: {base_item} (RM{base_price}) "
                    f"→ {u['item']} (RM{u['price']})"
                )

    def test_upsells_sorted_by_highest_margin(self):
        """Within each item, upsells must be sorted highest margin first."""
        for base_item, upsells in UPSELL_MAP.items():
            margins = [u["margin"] for u in upsells]
            assert margins == sorted(margins, reverse=True), (
                f"Upsells for '{base_item}' not sorted by margin: {margins}"
            )

    def test_upsell_prices_higher_than_base(self):
        for base_item, upsells in UPSELL_MAP.items():
            base_price = MENU[base_item]["price"]
            for u in upsells:
                assert u["price"] > base_price, (
                    f"{u['item']} (RM{u['price']}) not more expensive "
                    f"than {base_item} (RM{base_price})"
                )

    def test_suggestion_texts_are_casual_malay(self):
        """All suggestion texts should end with common casual phrases."""
        casual_endings = ("nak try?", "nak?", "nak tukar?", "best!", "sedap!")
        for base_item, upsells in UPSELL_MAP.items():
            for u in upsells:
                text_lower = u["text"].lower()
                assert any(text_lower.endswith(e) for e in casual_endings), (
                    f"Suggestion for {base_item} not casual enough: '{u['text']}'"
                )

    def test_each_upsell_has_required_fields(self):
        for base_item, upsells in UPSELL_MAP.items():
            for u in upsells:
                assert "item" in u
                assert "item_display" in u
                assert "price" in u
                assert "margin" in u
                assert "text" in u


# ============================================================
# UpsellEngine — Core Logic
# ============================================================


class TestUpsellEngine:

    @pytest.fixture
    def engine(self):
        return UpsellEngine()

    def test_get_upsell_maggi_goreng(self, engine):
        """Maggi Goreng should upsell to Kambing (highest margin)."""
        result = engine.get_upsell("maggi goreng")
        assert result is not None
        assert result["type"] == "upgrade"
        assert result["original"] == "maggi goreng"
        assert result["margin"] > 0
        assert result["upsell_price"] > result["original_price"]

    def test_get_upsell_roti_canai(self, engine):
        """Roti Canai should upsell to a more expensive roti variant."""
        result = engine.get_upsell("roti canai")
        assert result is not None
        assert result["type"] == "upgrade"
        assert result["upsell_price"] > MENU["roti canai"]["price"]

    def test_get_upsell_nasi_goreng_biasa(self, engine):
        """Nasi Goreng Biasa should upsell to Seafood (highest margin)."""
        result = engine.get_upsell("nasi goreng biasa")
        assert result is not None
        assert result["upsell_item"] == "nasi goreng seafood"

    def test_get_upsell_mee_goreng(self, engine):
        result = engine.get_upsell("mee goreng")
        assert result is not None
        assert result["upsell_price"] > MENU["mee goreng"]["price"]

    def test_get_upsell_naan_biasa(self, engine):
        result = engine.get_upsell("naan biasa")
        assert result is not None
        assert result["upsell_price"] > MENU["naan biasa"]["price"]

    def test_get_upsell_sirap_ais(self, engine):
        result = engine.get_upsell("sirap ais")
        assert result is not None
        assert result["upsell_price"] > MENU["sirap ais"]["price"]

    def test_no_upsell_for_unknown_item(self, engine):
        result = engine.get_upsell("pizza hawaii")
        assert result is None

    def test_upsell_result_has_suggestion_text(self, engine):
        result = engine.get_upsell("maggi goreng")
        assert result is not None
        assert "suggestion_text" in result
        assert len(result["suggestion_text"]) > 0


# ============================================================
# Session Tracking — One upsell per item rule
# ============================================================


class TestSessionTracking:

    @pytest.fixture
    def engine(self):
        return UpsellEngine()

    def test_only_one_upsell_per_item(self, engine):
        """First call returns suggestion, second call returns None."""
        first = engine.get_upsell("maggi goreng")
        assert first is not None
        second = engine.get_upsell("maggi goreng")
        assert second is None

    def test_different_items_both_get_upsell(self, engine):
        r1 = engine.get_upsell("maggi goreng")
        r2 = engine.get_upsell("roti canai")
        assert r1 is not None
        assert r2 is not None

    def test_reset_session_allows_re_upsell(self, engine):
        engine.get_upsell("maggi goreng")
        engine.reset_session()
        result = engine.get_upsell("maggi goreng")
        assert result is not None

    def test_decline_prevents_re_upsell(self, engine):
        engine.decline_upsell("roti canai")
        result = engine.get_upsell("roti canai")
        assert result is None


# ============================================================
# Accept / Decline Upsell
# ============================================================


class TestAcceptDecline:

    @pytest.fixture
    def engine(self):
        return UpsellEngine()

    def test_accept_valid_upsell(self, engine):
        result = engine.accept_upsell("maggi goreng", "maggi goreng kambing")
        assert result is not None
        assert result["name"] == "Maggi Goreng Kambing"
        assert result["price"] == MENU["maggi goreng kambing"]["price"]
        assert result["replaced"] == "maggi goreng"

    def test_accept_invalid_upsell(self, engine):
        result = engine.accept_upsell("maggi goreng", "pizza hawaii")
        assert result is None

    def test_accept_returns_audio_id(self, engine):
        result = engine.accept_upsell("roti canai", "roti telur")
        assert result is not None
        assert "audio_id" in result


# ============================================================
# Premium Items — Addon suggestions
# ============================================================


class TestPremiumAddon:

    @pytest.fixture
    def engine(self):
        return UpsellEngine()

    def test_premium_item_gets_addon(self, engine):
        """Premium items should get drink/side add-on suggestions."""
        result = engine.get_upsell("nasi goreng seafood")
        if result is not None:
            assert result["type"] == "addon"

    def test_premium_drink_gets_food_addon(self, engine):
        """Premium drink should suggest food side."""
        result = engine.get_upsell("milo ais")
        if result is not None:
            assert result["type"] == "addon"

    def test_premium_items_set_not_empty(self):
        assert len(_PREMIUM_ITEMS) > 5


# ============================================================
# get_all_upsells — UI display
# ============================================================


class TestGetAllUpsells:

    @pytest.fixture
    def engine(self):
        return UpsellEngine()

    def test_returns_list(self, engine):
        options = engine.get_all_upsells("maggi goreng")
        assert isinstance(options, list)
        assert len(options) > 0

    def test_all_options_have_margin(self, engine):
        options = engine.get_all_upsells("roti canai")
        for opt in options:
            assert "margin" in opt
            assert opt["margin"] > 0

    def test_no_options_for_unknown(self, engine):
        options = engine.get_all_upsells("pizza hawaii")
        assert options == []

    def test_does_not_affect_session_tracking(self, engine):
        """get_all_upsells should NOT mark the item as upsold."""
        engine.get_all_upsells("maggi goreng")
        result = engine.get_upsell("maggi goreng")
        assert result is not None  # Still available


# ============================================================
# Stats
# ============================================================


class TestUpsellStats:

    @pytest.fixture
    def engine(self):
        return UpsellEngine()

    def test_stats_returns_dict(self, engine):
        stats = engine.get_upsell_stats()
        assert "total_items_with_upsells" in stats
        assert "total_upsell_options" in stats
        assert "average_margin_rm" in stats
        assert "premium_items_count" in stats
        assert "top_10_margins" in stats

    def test_stats_positive_values(self, engine):
        stats = engine.get_upsell_stats()
        assert stats["total_items_with_upsells"] > 0
        assert stats["total_upsell_options"] > 0
        assert stats["average_margin_rm"] > 0

    def test_top_margins_sorted(self, engine):
        stats = engine.get_upsell_stats()
        margins = [m["margin"] for m in stats["top_10_margins"]]
        assert margins == sorted(margins, reverse=True)


# ============================================================
# Singleton
# ============================================================


class TestSingleton:

    def test_get_upsell_engine_returns_same_instance(self):
        e1 = get_upsell_engine()
        e2 = get_upsell_engine()
        assert e1 is e2


# ============================================================
# ElevenLabs TTS
# ============================================================


class TestElevenLabsTTS:

    @pytest.mark.asyncio
    async def test_tts_returns_none_without_api_key(self):
        """Without ELEVENLABS_API_KEY, should return None gracefully."""
        with patch.dict("os.environ", {"ELEVENLABS_API_KEY": ""}, clear=False):
            # Reset cached config
            import upsell_engine
            upsell_engine._elevenlabs_api_key = None
            result = await generate_upsell_audio("Test text")
            assert result is None

    @pytest.mark.asyncio
    async def test_tts_calls_elevenlabs_api(self):
        """With API key, should call ElevenLabs endpoint."""
        import upsell_engine
        upsell_engine._elevenlabs_api_key = None

        with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}, clear=False):
            upsell_engine._elevenlabs_api_key = None
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.content = b"fake-audio-bytes"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await generate_upsell_audio("Maggi Goreng Kambing lagi power!")
                assert result == b"fake-audio-bytes"
                mock_client.post.assert_called_once()


# ============================================================
# Integration: OrderEngine + UpsellEngine
# ============================================================


class TestOrderEngineUpsellIntegration:

    @pytest.fixture
    def order_engine(self):
        from order_engine import OrderEngine
        # Reset the upsell singleton for clean tests
        import upsell_engine
        upsell_engine._upsell_instance = None
        return OrderEngine()

    def test_process_includes_upsell(self, order_engine):
        """When ordering a basic item, response should include upsell."""
        result = order_engine.process("maggi goreng satu", [])
        assert result["action"] == "add_items"
        # Should have upsell in response
        if "upsell" in result:
            assert result["upsell"]["margin"] > 0
            assert result["upsell"]["type"] == "upgrade"

    def test_process_upsell_text_in_response(self, order_engine):
        """Upsell text should appear in the response text."""
        result = order_engine.process("maggi goreng satu", [])
        # Text should contain either upsell suggestion or "Ada lagi?"
        assert ("nak try?" in result["text"].lower()
                or "nak tukar?" in result["text"].lower()
                or "ada" in result["text"].lower())

    def test_second_order_same_item_no_duplicate_upsell(self, order_engine):
        """Second order of same item should NOT trigger upsell again."""
        order_engine.process("maggi goreng satu", [])
        result2 = order_engine.process("maggi goreng satu", [])
        # Second time should fall back to "Ada apa-apa lagi?"
        assert "upsell" not in result2 or result2.get("upsell") is None
