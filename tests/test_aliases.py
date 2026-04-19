"""Tests for Change 3 — Whisper alias normalization.

apply_aliases() is a pure string transform invoked at the top of
validate_menu_item(). Tests cover the helper directly plus one
end-to-end integration against the validator.
"""
from menu_validator import ALIASES, apply_aliases, validate_menu_item


def test_tioys_to_teh_ais():
    """Production-observed mishearing: 'tioys' must resolve to 'teh ais'."""
    assert apply_aliases("tioys") == "teh ais"


def test_full_phrase_match():
    """Multi-word aliases resolve via exact full-phrase lookup, not tokens."""
    assert apply_aliases("signati jambu") == "sirap jambu"


def test_token_replacement():
    """Inputs that aren't a full-phrase key fall back to per-token remap."""
    assert apply_aliases("minggoreng satu") == "mee goreng satu"


def test_unchanged_valid_item():
    """Already-canonical inputs pass through unchanged (no false rewrites)."""
    assert apply_aliases("teh tarik") == "teh tarik"


def test_case_insensitive():
    """Alias lookup is case-insensitive — uppercase normalizes first."""
    assert apply_aliases("TIOYS") == "teh ais"


def test_whitespace_handling():
    """Leading/trailing whitespace is stripped before alias lookup."""
    assert apply_aliases("  tioys  ") == "teh ais"


def test_multiple_aliases_in_sentence():
    """Per-token remap handles multiple single-token aliases in one string."""
    assert (
        apply_aliases("dua minggoreng dengan tehais")
        == "dua mee goreng dengan teh ais"
    )


def test_integration_validate_menu_item():
    """End-to-end: validate_menu_item applies aliases then matches the menu.

    'tioys' alias-normalizes to 'teh ais', which is an exact key in MENU,
    so the validator returns valid=True with the canonical item_key.
    """
    result = validate_menu_item("tioys")
    assert result["valid"] is True
    assert result["item_key"] == "teh ais"
