"""
Guard-rail tests for ICONIC_DRINKS_FLOOR.

The 06-Apr-2026 POS export missed several universally-ordered drinks.
apply_popularity_floor() patches their popularity so downstream consumers
(fuzzy-match tie-break, top-30 prompt injection) don't demote them to zero.

These tests verify:
  1. The floor is applied at MENU load time (teh tarik has a non-zero pop).
  2. The floor never lowers an existing popularity value.
  3. Items not listed in ICONIC_DRINKS_FLOOR are untouched.
"""
from order_engine import MENU, ICONIC_DRINKS_FLOOR, apply_popularity_floor


def test_teh_tarik_has_floor_applied():
    assert "teh tarik" in MENU, "teh tarik missing from MENU"
    assert MENU["teh tarik"]["popularity"] >= ICONIC_DRINKS_FLOOR["teh tarik"], (
        f"teh tarik popularity {MENU['teh tarik']['popularity']} is below "
        f"the floor {ICONIC_DRINKS_FLOOR['teh tarik']}"
    )


def test_floor_never_lowers_existing_pop():
    # Synthetic menu: one item already above its floor, one below.
    menu = {
        "teh tarik":  {"popularity": 200, "price": 2.00, "audio_id": "", "category": "drink"},
        "milo panas": {"popularity":   0, "price": 2.80, "audio_id": "", "category": "drink"},
    }
    apply_popularity_floor(menu)

    assert menu["teh tarik"]["popularity"] == 200, \
        "apply_popularity_floor lowered an existing higher popularity"
    assert menu["milo panas"]["popularity"] == ICONIC_DRINKS_FLOOR["milo panas"], \
        "apply_popularity_floor did not raise a below-floor value"


def test_unlisted_items_unchanged():
    # Synthetic menu mixing listed and unlisted items — the floor must
    # only touch items explicitly in ICONIC_DRINKS_FLOOR.
    menu = {
        "roti canai":  {"popularity":  60, "price": 1.50, "audio_id": "", "category": "bread"},
        "ais kosong":  {"popularity": 133, "price": 0.30, "audio_id": "", "category": "drink"},
        "teh o ais":   {"popularity":  99, "price": 2.10, "audio_id": "", "category": "drink"},
        "some_phantom_item_with_zero_pop": {
            "popularity": 0, "price": 0.0, "audio_id": "", "category": "other",
        },
    }
    originals = {k: v["popularity"] for k, v in menu.items()}

    apply_popularity_floor(menu)

    for name, original_pop in originals.items():
        assert name not in ICONIC_DRINKS_FLOOR, \
            f"test assumption broken: {name!r} is in ICONIC_DRINKS_FLOOR"
        assert menu[name]["popularity"] == original_pop, (
            f"{name!r} popularity changed from {original_pop} to "
            f"{menu[name]['popularity']} — floor is touching items it shouldn't"
        )
