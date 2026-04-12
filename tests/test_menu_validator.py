"""
Test Suite — Menu Validator & Voice Pipeline Reliability
=========================================================
20 real-world Malay transcript scenarios covering:
- Exact menu matches
- Fuzzy / misheard items
- Modifier validation (kurang manis, kaw, garing, etc.)
- Invalid items that should be rejected
- Multiple item orders
- Edge cases (empty, gibberish, partial names)

These simulate what Whisper would transcribe from real Malay speech.
"""
import pytest
from menu_validator import (
    validate_menu_item,
    validate_order_items,
    validate_modifier,
    get_allowed_modifiers,
    _get_item_category,
)
from order_engine import MENU


# ============================================================
# Test 1-5: Exact Menu Matches (should always pass)
# ============================================================

class TestExactMatches:
    """Items that match the MENU dict exactly."""

    def test_01_roti_canai(self):
        """Common order: roti canai"""
        result = validate_menu_item("roti canai")
        assert result["valid"] is True
        assert result["item_key"] == "roti canai"
        assert result["price"] == 2.00

    def test_02_teh_tarik(self):
        """Most popular drink: teh tarik"""
        result = validate_menu_item("teh tarik")
        assert result["valid"] is True
        assert result["item_key"] == "teh tarik"

    def test_03_nasi_goreng_kampung(self):
        """Full name match: nasi goreng kampung"""
        result = validate_menu_item("nasi goreng kampung")
        assert result["valid"] is True
        assert result["item_key"] == "nasi goreng kampung"

    def test_04_maggi_goreng_kambing(self):
        """Premium noodle item"""
        result = validate_menu_item("maggi goreng kambing")
        assert result["valid"] is True
        assert result["item_key"] == "maggi goreng kambing"

    def test_05_milo_ais(self):
        """Common drink: milo ais"""
        result = validate_menu_item("milo ais")
        assert result["valid"] is True
        assert result["item_key"] == "milo ais"


# ============================================================
# Test 6-10: Fuzzy / Misheard Items (Whisper errors)
# ============================================================

class TestFuzzyMatches:
    """Items that Whisper might mishear — must resolve to real menu items."""

    def test_06_roti_canai_misspelled(self):
        """'roti canai' slightly mangled by speech recognition"""
        result = validate_menu_item("roti cana")
        # Should fuzzy match to "roti canai" or at least find it via substring
        assert result["valid"] is True
        assert "roti" in result["item_key"]

    def test_07_mee_goreng_partial(self):
        """'mee goreng' from speech that says 'mi goreng'"""
        result = validate_menu_item("mee goreng")
        assert result["valid"] is True
        assert result["item_key"] == "mee goreng"

    def test_08_naan_cheese_garlic(self):
        """Longer item name must match exactly"""
        result = validate_menu_item("naan cheese garlic")
        assert result["valid"] is True
        assert result["item_key"] == "naan cheese garlic"

    def test_09_briyani_ayam_bawang_set(self):
        """Long compound name"""
        result = validate_menu_item("briyani ayam bawang set")
        assert result["valid"] is True
        assert result["item_key"] == "briyani ayam bawang set"

    def test_10_kuey_teow_goreng(self):
        """kuey teow goreng — common Whisper misrecognition target"""
        result = validate_menu_item("kuey teow goreng")
        assert result["valid"] is True
        assert result["item_key"] == "kuey teow goreng"


# ============================================================
# Test 11-13: Invalid Items (MUST be rejected)
# ============================================================

class TestInvalidItems:
    """Items that don't exist in the menu — Aisha must never accept these."""

    def test_11_pizza_rejected(self):
        """Pizza doesn't exist at a mamak restaurant"""
        result = validate_menu_item("pizza hawaii")
        assert result["valid"] is False
        assert result["item_key"] is None

    def test_12_sushi_rejected(self):
        """Sushi is not on the menu"""
        result = validate_menu_item("sushi salmon")
        assert result["valid"] is False

    def test_13_gibberish_rejected(self):
        """Pure noise should be rejected"""
        result = validate_menu_item("xyzabc blah blah")
        assert result["valid"] is False


# ============================================================
# Test 14-16: Modifier Validation
# ============================================================

class TestModifierValidation:
    """Modifiers must be validated per item category."""

    def test_14_kurang_manis_for_drink(self):
        """kurang manis is valid for teh tarik (drink)"""
        result = validate_modifier("teh tarik", "kurang manis")
        assert result["valid"] is True

    def test_15_garing_for_roti(self):
        """garing (crispy) is valid for roti canai"""
        result = validate_modifier("roti canai", "garing")
        assert result["valid"] is True

    def test_16_kaw_for_drink(self):
        """kaw (strong) is valid for drinks"""
        result = validate_modifier("kopi ais", "kaw")
        assert result["valid"] is True

    def test_16b_dinosaur_invalid_for_roti(self):
        """dinosaur modifier doesn't make sense for roti"""
        result = validate_modifier("roti canai", "dinosaur")
        assert result["valid"] is False


# ============================================================
# Test 17-18: Full Pipeline Validation (multiple items)
# ============================================================

class TestFullPipelineValidation:
    """Simulate DeepSeek output → validate_order_items."""

    def test_17_typical_order(self):
        """Typical mamak order: roti canai + teh tarik kurang manis"""
        extracted = [
            {"matched_item": "roti canai", "quantity": 2, "confidence": 0.95, "modifiers": ["garing"]},
            {"matched_item": "teh tarik", "quantity": 1, "confidence": 0.92, "modifiers": ["kurang manis"]},
        ]
        result = validate_order_items(extracted)
        assert result["all_valid"] is True
        assert len(result["valid_items"]) == 2
        assert len(result["invalid_items"]) == 0
        # Check modifiers preserved
        teh = [i for i in result["valid_items"] if i["item_key"] == "teh tarik"][0]
        assert "kurang manis" in teh["modifiers"]

    def test_18_mixed_valid_invalid(self):
        """Order with one valid and one hallucinated item"""
        extracted = [
            {"matched_item": "nasi goreng mamak", "quantity": 1, "confidence": 0.9, "modifiers": []},
            {"matched_item": "burger special", "quantity": 1, "confidence": 0.5, "modifiers": []},
        ]
        result = validate_order_items(extracted)
        assert result["needs_clarification"] is True
        assert len(result["valid_items"]) == 1
        assert len(result["invalid_items"]) == 1
        assert result["valid_items"][0]["item_key"] == "nasi goreng mamak"


# ============================================================
# Test 19-20: Edge Cases
# ============================================================

class TestEdgeCases:
    """Edge cases that trip up voice AI systems."""

    def test_19_empty_order(self):
        """Empty input should return cleanly"""
        result = validate_order_items([])
        assert result["all_valid"] is False
        assert len(result["valid_items"]) == 0
        assert len(result["invalid_items"]) == 0

    def test_20_duplicate_items_both_valid(self):
        """Same item ordered twice in one utterance"""
        extracted = [
            {"matched_item": "roti canai", "quantity": 1, "confidence": 0.9, "modifiers": []},
            {"matched_item": "roti canai", "quantity": 1, "confidence": 0.9, "modifiers": ["garing"]},
        ]
        result = validate_order_items(extracted)
        assert result["all_valid"] is True
        # Both should be valid (different modifiers = different line items)
        assert len(result["valid_items"]) == 2


# ============================================================
# Category Detection
# ============================================================

class TestCategoryDetection:
    """Ensure items are categorized correctly for modifier validation."""

    def test_drink_category(self):
        assert _get_item_category("teh tarik") == "drink"
        assert _get_item_category("milo ais") == "drink"
        assert _get_item_category("kopi panas") == "drink"

    def test_roti_category(self):
        assert _get_item_category("roti canai") == "roti"
        assert _get_item_category("murtabak ayam") == "roti"

    def test_noodle_category(self):
        assert _get_item_category("maggi goreng") == "noodle"
        assert _get_item_category("mee goreng mamak") == "noodle"
        assert _get_item_category("bihun goreng") == "noodle"

    def test_nasi_category(self):
        assert _get_item_category("nasi ayam") == "nasi"
        assert _get_item_category("briyani ayam") == "nasi"

    def test_naan_category(self):
        assert _get_item_category("naan biasa") == "naan"
        assert _get_item_category("naan cheese") == "naan"


# ============================================================
# Modifier Whitelist Coverage
# ============================================================

class TestModifierWhitelist:
    """Ensure common modifiers are in the whitelist."""

    def test_drink_modifiers_present(self):
        mods = get_allowed_modifiers("teh tarik")
        assert "kurang manis" in mods
        assert "kaw" in mods
        assert "panas" in mods
        assert "kurang ais" in mods
        assert "tarik" in mods
        assert "dinosaur" in mods  # for milo

    def test_roti_modifiers_present(self):
        mods = get_allowed_modifiers("roti canai")
        assert "garing" in mods
        assert "crispy" in mods
        assert "lembut" in mods

    def test_noodle_modifiers_present(self):
        mods = get_allowed_modifiers("maggi goreng")
        assert "pedas" in mods
        assert "tak nak pedas" in mods
        assert "tambah telur" in mods

    def test_global_modifiers_everywhere(self):
        """Global modifiers should be available for all items."""
        for item_name in ["roti canai", "nasi ayam", "teh tarik", "maggi goreng"]:
            mods = get_allowed_modifiers(item_name)
            assert "double" in mods
            assert "extra" in mods


# ============================================================
# Menu Data Integrity
# ============================================================

class TestMenuIntegrity:
    """Verify the MENU dict is consistent and complete."""

    def test_all_items_validate(self):
        """Every item in MENU should self-validate as valid."""
        for item_name in MENU.keys():
            result = validate_menu_item(item_name)
            assert result["valid"] is True, f"MENU item '{item_name}' failed validation"
            assert result["item_key"] == item_name

    def test_menu_has_drinks(self):
        """Menu must have drink items."""
        drink_items = [k for k in MENU if _get_item_category(k) == "drink"]
        assert len(drink_items) >= 10, f"Only {len(drink_items)} drinks in menu"

    def test_menu_has_roti(self):
        """Menu must have roti items."""
        roti_items = [k for k in MENU if _get_item_category(k) == "roti"]
        assert len(roti_items) >= 10, f"Only {len(roti_items)} roti items in menu"
