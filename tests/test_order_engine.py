# tests/test_order_engine.py
"""
P0 PRIORITY — Core business logic. Wrong extraction = wrong orders = lost money.
Tests the greedy longest-match algorithm against 143+ menu items.
"""
import pytest
from order_engine import OrderEngine, MENU, MALAY_NUMBERS, END_PHRASES, _SORTED_KEYS


@pytest.fixture
def engine():
    return OrderEngine()


# ============================================================
# _extract_items — THE most critical function
# ============================================================


class TestExtractItems:
    """Tests for _extract_items() — greedy longest-match algorithm."""

    # ── Basic single-item extraction ──

    def test_extract_roti_canai(self, engine):
        result = engine._extract_items("roti canai satu")
        assert len(result) >= 1
        assert result[0][0] == "roti canai"
        assert result[0][1] == 1  # qty

    def test_extract_naan_butter_garlic(self, engine):
        result = engine._extract_items("naan butter garlic")
        names = [r[0] for r in result]
        assert "naan butter garlic" in names

    def test_extract_maggi_goreng(self, engine):
        result = engine._extract_items("maggi goreng satu")
        names = [r[0] for r in result]
        assert "maggi goreng" in names

    def test_extract_mee_goreng(self, engine):
        result = engine._extract_items("mee goreng mamak")
        names = [r[0] for r in result]
        assert "mee goreng mamak" in names

    # ── Greedy longest-match ──

    def test_greedy_roti_canai_susu(self):
        """'roti canai susu' must NOT match as 'roti canai' + leftover 'susu'"""
        result = OrderEngine._extract_items("roti canai susu")
        names = [r[0] for r in result]
        assert "roti canai susu" in names
        # Should be 1 item, not 2
        assert len(result) == 1

    def test_greedy_naan_cheese_garlic(self):
        """'naan cheese garlic' should match the longest menu key available"""
        result = OrderEngine._extract_items("naan cheese garlic")
        names = [r[0] for r in result]
        assert "naan cheese garlic" in names
        assert len(result) == 1

    def test_greedy_maggi_goreng_kambing(self):
        """'maggi goreng kambing' must be one item, not 'maggi goreng' + unknown"""
        result = OrderEngine._extract_items("maggi goreng kambing")
        names = [r[0] for r in result]
        assert "maggi goreng kambing" in names
        assert len(result) == 1

    def test_greedy_nasi_goreng_kampung(self):
        result = OrderEngine._extract_items("nasi goreng kampung")
        names = [r[0] for r in result]
        assert "nasi goreng kampung" in names
        assert len(result) == 1

    def test_greedy_briyani_ayam_bawang_set(self):
        """Longest match: 'briyani ayam bawang set' not split"""
        result = OrderEngine._extract_items("briyani ayam bawang set")
        names = [r[0] for r in result]
        assert "briyani ayam bawang set" in names
        assert len(result) == 1

    def test_greedy_roti_telur_bawang(self):
        """'roti telur bawang' should match as one, not 'roti telur' + leftover"""
        result = OrderEngine._extract_items("roti telur bawang")
        names = [r[0] for r in result]
        assert "roti telur bawang" in names
        assert len(result) == 1

    # ── Multiple items ──

    def test_extract_multiple_items(self, engine):
        result = engine._extract_items("roti canai satu maggi goreng satu")
        names = [r[0] for r in result]
        assert "roti canai" in names
        assert "maggi goreng" in names
        assert len(result) == 2

    def test_extract_food_and_drink(self, engine):
        result = engine._extract_items("roti canai satu kambing mysur satu")
        names = [r[0] for r in result]
        assert "roti canai" in names
        assert "kambing mysur" in names

    # ── Edge cases ──

    def test_extract_empty_string(self, engine):
        result = engine._extract_items("")
        assert result == []

    def test_extract_noise_only(self, engine):
        """Pure gibberish should return empty"""
        result = engine._extract_items("errr hmm uhh bla bla")
        assert result == []

    def test_extract_unknown_item(self, engine):
        """Item not in menu should not appear"""
        result = engine._extract_items("pizza hawaii satu")
        assert all(r[0] != "pizza hawaii" for r in result)

    def test_extract_handles_extra_whitespace(self, engine):
        result = engine._extract_items("  roti   canai   satu  ")
        names = [r[0] for r in result]
        assert "roti canai" in names


# ============================================================
# Quantity Parsing
# ============================================================


class TestQuantityParsing:
    """Malay number words must map to correct integers."""

    def test_satu(self, engine):
        result = engine._extract_items("roti canai satu")
        assert result[0][1] == 1

    def test_dua(self, engine):
        result = engine._extract_items("roti canai dua")
        assert result[0][1] == 2

    def test_tiga(self, engine):
        result = engine._extract_items("maggi goreng tiga")
        assert result[0][1] == 3

    def test_empat(self, engine):
        result = engine._extract_items("roti canai empat")
        assert result[0][1] == 4

    def test_lima(self, engine):
        result = engine._extract_items("naan biasa lima")
        assert result[0][1] == 5

    def test_numeric_digit(self, engine):
        result = engine._extract_items("roti canai 2")
        assert result[0][1] == 2

    def test_default_qty_one(self, engine):
        """No quantity specified → default to 1"""
        result = engine._extract_items("roti canai")
        assert result[0][1] == 1

    def test_quantity_before_item(self, engine):
        """'dua roti canai' should also work"""
        result = engine._extract_items("dua roti canai")
        assert result[0][1] == 2

    def test_numeric_before_item(self, engine):
        """'3 naan biasa'"""
        result = engine._extract_items("3 naan biasa")
        assert result[0][1] == 3


# ============================================================
# End-of-order detection
# ============================================================


class TestEndOfOrderDetection:
    """End phrases must be correctly identified. False positives cut orders short."""

    @pytest.mark.parametrize("phrase", [
        "tu je", "tu jer", "itu je", "cukup", "dah",
        "habis", "sekian", "confirm", "settle", "setel",
        "sudah", "dah cukup", "itu sahaja",
    ])
    def test_detects_end_phrases(self, engine, phrase):
        assert engine._matches_phrase(phrase, END_PHRASES) is True

    @pytest.mark.parametrize("phrase", [
        "roti canai", "nak tambah lagi", "milo ais dua",
        "nasi goreng kampung", "ada lagi",
    ])
    def test_not_end_phrases(self, engine, phrase):
        assert engine._matches_phrase(phrase, END_PHRASES) is False


# ============================================================
# process() — Full pipeline
# ============================================================


class TestProcess:
    """Integration test: process() method end-to-end."""

    def test_process_single_item(self, engine):
        result = engine.process("roti canai satu", [])
        assert result["action"] == "add_items"
        assert len(result["new_items"]) == 1
        assert result["new_items"][0]["name"] == "Roti Canai"
        assert result["new_items"][0]["qty"] == 1
        assert result["total"] > 0

    def test_process_empty_input(self, engine):
        result = engine.process("", [])
        assert result["action"] == "unknown"
        assert "ulang" in result["text"].lower()

    def test_process_end_phrase_with_order(self, engine):
        current = [{"name": "Roti Canai", "qty": 1, "price": 2.00}]
        result = engine.process("tu je", current)
        assert result["action"] == "confirm_order"
        assert result["total"] == 2.00

    def test_process_end_phrase_empty_order(self, engine):
        result = engine.process("tu je", [])
        assert result["action"] == "no_items"

    def test_process_gibberish(self, engine):
        result = engine.process("xyzabc123", [])
        assert result["action"] == "unknown"

    def test_process_merges_into_existing_order(self, engine):
        current = [{"name": "Roti Canai", "qty": 1, "price": 2.00}]
        result = engine.process("maggi goreng satu", current)
        assert result["action"] == "add_items"
        # Order should contain both items
        names = [i["name"].lower() for i in result["order"]]
        assert "roti canai" in names
        assert "maggi goreng" in names

    def test_process_increments_qty_on_duplicate(self, engine):
        current = [{"name": "Roti Canai", "qty": 1, "price": 2.00}]
        result = engine.process("roti canai satu", current)
        # existing roti canai should now be qty 2
        roti = [i for i in result["order"] if i["name"].lower() == "roti canai"][0]
        assert roti["qty"] == 2

    def test_process_audio_ids_present(self, engine):
        result = engine.process("roti canai", [])
        assert "audio_ids" in result
        assert len(result["audio_ids"]) >= 1
        # Should include "ada lagi?" audio
        assert "0043" in result["audio_ids"]


# ============================================================
# Response building
# ============================================================


class TestResponseBuilding:
    """_build_confirm and _build_add_items must produce correct output."""

    def test_build_confirm_single(self, engine):
        order = [{"name": "Roti Canai", "qty": 1, "price": 2.00}]
        result = engine._build_confirm(order)
        assert result["action"] == "confirm_order"
        assert result["total"] == 2.00
        assert "0021" in result["audio_ids"]  # terima kasih audio

    def test_build_confirm_multiple(self, engine):
        order = [
            {"name": "Roti Canai", "qty": 2, "price": 2.00},
            {"name": "Maggi Goreng", "qty": 1, "price": 6.00},
        ]
        result = engine._build_confirm(order)
        assert result["total"] == 10.00  # 2*2 + 1*6

    def test_build_confirm_empty_order(self, engine):
        result = engine._build_confirm([])
        assert result["action"] == "no_items"

    def test_add_items_includes_ada_lagi(self, engine):
        found = [("roti canai", 1, "0051", 2.00)]
        result = engine._build_add_items(found, [])
        assert "0043" in result["audio_ids"]  # Ada lagi?
        assert "Ada" in result["text"]


# ============================================================
# Greeting
# ============================================================


class TestGreeting:
    """Time-based greeting must be correct."""

    def test_greeting_returns_dict(self, engine):
        result = engine.get_greeting()
        assert "text" in result
        assert "audio_ids" in result
        assert len(result["audio_ids"]) == 1

    def test_greeting_has_aisha(self, engine):
        result = engine.get_greeting()
        assert "Aisha" in result["text"] or "aisha" in result["text"].lower()


# ============================================================
# Ambiguous items detection
# ============================================================


class TestAmbiguousItems:
    """Items like 'ayam bawang' that match multiple longer items."""

    def test_ayam_bawang_is_ambiguous(self, engine):
        """'ayam bawang' appears in 'nasi ayam bawang' and 'briyani ayam bawang'"""
        found = [("ayam bawang", 1, "0248", 7.00)]
        ambiguous = engine._find_ambiguous(found)
        assert len(ambiguous) > 0

    def test_roti_canai_not_ambiguous_vs_susu(self, engine):
        """'roti canai' vs 'roti canai susu' — same first word, NOT ambiguous"""
        found = [("roti canai", 1, "0051", 2.00)]
        ambiguous = engine._find_ambiguous(found)
        assert len(ambiguous) == 0

    def test_naan_biasa_not_ambiguous(self, engine):
        """'naan biasa' is the only item starting with 'naan biasa'"""
        found = [("naan biasa", 1, "0111", 3.00)]
        ambiguous = engine._find_ambiguous(found)
        assert len(ambiguous) == 0


# ============================================================
# Data integrity
# ============================================================


class TestMenuData:
    """Verify the MENU dict and supporting data structures."""

    def test_menu_not_empty(self):
        assert len(MENU) > 80  # OrderEngine MENU has 94 items

    def test_all_items_have_price(self):
        for name, item in MENU.items():
            assert "price" in item
            assert item["price"] > 0, f"{name} has zero/negative price"

    def test_all_items_have_audio_id_key(self):
        for name, item in MENU.items():
            assert "audio_id" in item

    def test_sorted_keys_longest_first(self):
        """_SORTED_KEYS must be sorted by length descending for greedy match"""
        for i in range(len(_SORTED_KEYS) - 1):
            assert len(_SORTED_KEYS[i]) >= len(_SORTED_KEYS[i + 1])

    def test_malay_numbers_complete(self):
        assert MALAY_NUMBERS["satu"] == 1
        assert MALAY_NUMBERS["dua"] == 2
        assert MALAY_NUMBERS["tiga"] == 3
        assert MALAY_NUMBERS["empat"] == 4
        assert MALAY_NUMBERS["lima"] == 5
        assert MALAY_NUMBERS["sepuluh"] == 10
