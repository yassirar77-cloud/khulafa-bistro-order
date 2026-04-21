"""
Menu Validator — Enterprise-grade grounding layer for Aisha voice ordering.
============================================================================
Every item Aisha extracts MUST pass through this module before being accepted.
No item reaches the order without matching a real menu entry.

Responsibilities:
1. Validate items against the canonical MENU dict (single source of truth)
2. Fuzzy-match misspelled/misheard items to real menu entries
3. Validate modifiers against a per-category whitelist
4. Return structured, validated output or flag items needing clarification
5. Log every validation step for observability
"""

import re
import json
import os
from datetime import datetime
from difflib import SequenceMatcher
from order_engine import MENU, _SORTED_KEYS


# ================================================================
# WHISPER PROMPT — Malaysian F&B vocabulary bias
# ================================================================
# Whisper's `prompt` parameter accepts up to 224 tokens of prior context
# that biases acoustic decoding toward the supplied vocabulary. We combine
# the top 15 food items by sales popularity (drinks and obvious sub-variants
# excluded) with an explicit PINNED_ITEMS list of drinks so Whisper hears
# the distinguishing words even when POS popularity under-counts them.
#
# Editors: to add an item, put it in PINNED_ITEMS and run the test suite
# (tests/test_whisper_prompt.py) — the token-budget test will fail if
# the combined prompt exceeds the 224-token ceiling.

# Drinks are excluded from the top-N food slice and instead pinned
# explicitly below. Detection is a simple keyword match on the item name.
DRINK_KEYWORDS = ["teh", "kopi", "milo", "ais", "air", "limau", "bandung",
                  "sirap", "nescafe", "horlick", "jus", "extra joss", "cincau", "barli"]


def is_drink(name: str) -> bool:
    return any(kw in name.lower() for kw in DRINK_KEYWORDS)


# Food sub-variants whose root form is already present in the top-N slice.
# Whisper biases on the root; dropping these frees tokens without losing
# coverage (the validator still resolves the full variant via MENU).
SKIP_FOOD_VARIANTS = {
    "nasi ayam sayur",          # root: nasi ayam
    "nasi ayam bawang sayur",   # root: nasi ayam bawang
    "maggi goreng telur mata",  # root: maggi goreng
}


# PINNED_ITEMS: manually pinned because MENU popularity data has a
# known import bug where hot drinks and iconic drinks (teh tarik,
# kopi panas, milo panas) show popularity=0 despite being common.
# Drinks need explicit pinning since they are short, acoustically
# similar words that Whisper frequently substitutes without biasing.
# See follow-up PR: "fix: reconcile hot/iced and tarik/plain
# popularity split from POS import"
PINNED_ITEMS = [
    # Teh family
    "teh tarik", "teh ais", "teh o", "teh o ais",
    # Kopi family
    "kopi ais", "kopi o", "kopi o ais", "kopi panas",
    # Milo family
    "milo ais", "milo panas",
    # Water
    "ais kosong", "air suam",
    # Other drinks
    "limau ais", "nescafe",
    # Food anchor
    "nasi goreng biasa",
]


def _compute_whisper_prompt() -> str:
    """Build the Malay F&B vocabulary prompt from MENU + PINNED_ITEMS.

    Takes the top 15 food items by popularity (drinks and known sub-variants
    excluded), appends PINNED_ITEMS, dedupes preserving order, and adds the
    modifier vocabulary suffix. Cached at module load by WHISPER_PROMPT below.
    """
    food_items = sorted(
        (
            (name, meta.get("popularity", 0))
            for name, meta in MENU.items()
            if not is_drink(name) and name not in SKIP_FOOD_VARIANTS
        ),
        key=lambda kv: kv[1],
        reverse=True,
    )[:15]
    top_food_names = [name for name, _ in food_items]

    combined: list[str] = []
    seen: set[str] = set()
    for name in top_food_names + PINNED_ITEMS:
        if name not in seen:
            combined.append(name)
            seen.add(name)

    return (
        "Menu Khulafa Bistro Malaysia: "
        + ", ".join(combined)
        + ". Modifiers: ais, panas, kurang manis, takeaway, tambah, kurang."
    )


# Cached at module load — input (MENU + PINNED_ITEMS) doesn't change per request.
WHISPER_PROMPT: str = _compute_whisper_prompt()


def get_whisper_prompt() -> str:
    """Return the cached Whisper vocabulary prompt (<224 tokens)."""
    return WHISPER_PROMPT


# ================================================================
# MODIFIER WHITELIST — per category
# ================================================================

# Global modifiers that apply to ALL items
_GLOBAL_MODIFIERS = {
    "tambah telur", "tambah sambal", "tambah sayur", "tambah cheese",
    "tambah keju", "tambah daging", "extra pedas", "pedas gila",
    "kurang pedas", "tak nak pedas", "pedas",
    "tak nak sayur", "tak nak sambal", "tak nak bawang", "tak nak cili",
    "tak nak kuah", "kering", "tak nak kacang", "tak nak timun",
    "tak nak telur", "tanpa sayur", "tanpa sambal", "tanpa bawang",
    "double", "extra", "besar", "kecil",
}

# Category-specific modifiers
_DRINK_MODIFIERS = {
    "kurang manis", "tak nak manis", "tanpa gula", "manis", "lebih manis",
    "sikit manis", "kaw", "kow", "pekat", "cair", "ringan",
    "kurang ais", "sikit ais", "tak nak ais", "tanpa ais",
    "banyak ais", "extra ice", "panas", "suam",
    "tarik", "tabur", "dinosaur", "dino",
    "besar", "jumbo", "kecil", "kosong",
}

_ROTI_MODIFIERS = {
    "garing", "crispy", "lembut", "well done", "masak betul",
    "setengah masak", "tak nak kuah", "kering",
    "tambah telur", "tambah cheese", "tambah keju",
    "double", "extra",
}

_NASI_MODIFIERS = {
    "kurang pedas", "tak nak pedas", "pedas", "extra pedas", "pedas gila",
    "tak nak sayur", "tak nak sambal", "tak nak bawang", "tak nak cili",
    "tak nak kuah", "kering", "tak nak kacang", "tak nak timun",
    "tambah telur", "tambah sambal", "tambah sayur",
    "tambah daging", "double", "extra",
}

_NOODLE_MODIFIERS = {
    "kurang pedas", "tak nak pedas", "pedas", "extra pedas", "pedas gila",
    "tak nak sayur", "tak nak bawang", "tak nak cili",
    "tambah telur", "tambah sambal", "tambah sayur",
    "garing", "crispy", "kering", "double", "extra",
    "tak nak telur",
}

_NAAN_MODIFIERS = {
    "garing", "crispy", "lembut", "double", "extra",
    "tambah cheese", "tambah keju",
}

_LAUK_MODIFIERS = {
    "kurang pedas", "tak nak pedas", "pedas", "extra pedas",
    "garing", "crispy", "well done",
    "tak nak kuah", "kering", "double",
}

# Map menu item categories to their allowed modifiers
def _get_item_category(item_name: str) -> str:
    """Determine the category of a menu item for modifier validation."""
    item = item_name.lower()
    if any(item.startswith(p) for p in ["teh", "kopi", "milo", "bandung", "sirap",
                                         "barli", "air", "cincau", "longan", "nescafe"]):
        return "drink"
    if any(item.startswith(p) for p in ["roti", "murtabak"]):
        return "roti"
    if any(item.startswith(p) for p in ["nasi goreng", "nasi g "]):
        return "noodle"  # nasi goreng is fried like noodles
    if item.startswith("nasi") or item.startswith("briyani"):
        return "nasi"
    if any(item.startswith(p) for p in ["maggi", "mee", "bihun", "kuey teow", "indomee"]):
        return "noodle"
    if any(item.startswith(p) for p in ["naan"]):
        return "naan"
    if any(item.startswith(p) for p in ["ayam", "kambing", "daging"]):
        return "lauk"
    return "general"

_CATEGORY_MODIFIERS = {
    "drink": _DRINK_MODIFIERS,
    "roti": _ROTI_MODIFIERS,
    "nasi": _NASI_MODIFIERS,
    "noodle": _NOODLE_MODIFIERS,
    "naan": _NAAN_MODIFIERS,
    "lauk": _LAUK_MODIFIERS,
    "general": set(),
}


def get_allowed_modifiers(item_name: str) -> set:
    """Get all allowed modifiers for a given menu item."""
    category = _get_item_category(item_name)
    return _GLOBAL_MODIFIERS | _CATEGORY_MODIFIERS.get(category, set())


def validate_modifier(item_name: str, modifier: str) -> dict:
    """
    Validate a single modifier against the whitelist for an item.

    Returns:
        {"valid": True, "modifier": "kurang manis"} or
        {"valid": False, "modifier": "xyz", "reason": "not allowed for roti items"}
    """
    mod_lower = modifier.lower().strip()
    allowed = get_allowed_modifiers(item_name)

    # Exact match
    if mod_lower in allowed:
        return {"valid": True, "modifier": mod_lower}

    # Fuzzy match — some modifiers may be slightly misheard
    best_score = 0
    best_match = None
    for allowed_mod in allowed:
        score = SequenceMatcher(None, mod_lower, allowed_mod).ratio()
        if score > best_score:
            best_score = score
            best_match = allowed_mod

    if best_score >= 0.8 and best_match:
        return {"valid": True, "modifier": best_match, "corrected_from": mod_lower}

    category = _get_item_category(item_name)
    return {
        "valid": False,
        "modifier": mod_lower,
        "reason": f"not allowed for {category} items",
        "category": category,
    }


# ================================================================
# MENU ITEM VALIDATION
# ================================================================

# ── Whisper alias normalization (Change 3) ──
# Whisper mishears common Malay F&B terms in predictable ways.
# Remap those BEFORE exact/greedy/fuzzy matching so the downstream
# pipeline sees canonical tokens. Safe by construction: if an alias
# maps incorrectly, the fuzzy matcher still gets to try.
ALIASES: dict[str, str] = {
    # Confirmed from production logs (April 2026)
    "tioys": "teh ais",
    "signati jambu": "sirap jambu",
    "signati": "sirap",
    "minggoreng": "mee goreng",
    "minggu ring": "mee goreng",
    "ming goreng": "mee goreng",
    "lima ais": "limau ais",
    "kuetiau": "kuey teow",
    "kuetiau goreng": "kuey teow goreng",
    # Common Whisper Malay confusions
    "maggie": "maggi",
    "maggie goreng": "maggi goreng",
    "cane": "canai",
    "canei": "canai",
    "nasik": "nasi",
    "mi goreng": "mee goreng",
    "tehais": "teh ais",
    "tehtarik": "teh tarik",
    "tehpanas": "teh panas",
    "kopio": "kopi o",
    "kopio ais": "kopi o ais",
    "miloais": "milo ais",
    "milopanas": "milo panas",
    # Pronunciation variants
    "ayam goring": "ayam goreng",
    "ayam goren": "ayam goreng",
    "daging goren": "daging goreng",
    "daging goring": "daging goreng",
    "martabak": "murtabak",
    "martabak ayam": "murtabak ayam",
    "martabak daging": "murtabak daging",
}


def apply_aliases(text: str) -> str:
    """Normalize Whisper Malay mishearings before menu matching.

    Full-phrase match wins over per-token replacement. Always returns
    lowercase, stripped, single-spaced text. Logs to stdout whenever an
    alias fires so the transformation is auditable in server logs.
    """
    text_lower = text.lower().strip()
    if text_lower in ALIASES:
        result = ALIASES[text_lower]
        print(f"[ALIAS] full-phrase: '{text_lower}' -> '{result}'")
        return result
    tokens = text_lower.split()
    normalized = [ALIASES.get(t, t) for t in tokens]
    result = " ".join(normalized)
    if result != text_lower:
        print(f"[ALIAS] token-level: '{text_lower}' -> '{result}'")
    return result


def validate_menu_item(item_name: str) -> dict:
    """
    Validate a single item against the MENU dict.

    Returns:
        {
            "valid": True,
            "item_key": "roti canai",      # canonical MENU key
            "price": 2.00,
            "audio_id": "0051",
            "corrected_from": None          # or original if fuzzy-matched
        }
        or
        {
            "valid": False,
            "item_key": None,
            "original": "pizza hawaii",
            "suggestions": ["roti pisang", "roti pisang cheese"],
            "reason": "not found in menu"
        }
    """
    item_lower = apply_aliases(item_name)

    # 1. Exact match
    if item_lower in MENU:
        m = MENU[item_lower]
        return {
            "valid": True,
            "item_key": item_lower,
            "price": m["price"],
            "audio_id": m["audio_id"],
            "corrected_from": None,
        }

    # 2. Greedy substring match (same logic as order_engine)
    length = len(item_lower)
    used = [False] * length
    matches = []

    for key in _SORTED_KEYS:
        klen = len(key)
        start = 0
        while start <= length - klen:
            idx = item_lower.find(key, start)
            if idx == -1:
                break
            if not any(used[idx:idx + klen]):
                matches.append(key)
                for i in range(idx, idx + klen):
                    used[i] = True
                start = idx + klen
            else:
                start = idx + 1

    if matches:
        # Return the first (longest) match
        best = matches[0]
        m = MENU[best]
        return {
            "valid": True,
            "item_key": best,
            "price": m["price"],
            "audio_id": m["audio_id"],
            "corrected_from": item_lower if best != item_lower else None,
        }

    # 3. Fuzzy match using SequenceMatcher — tie-break by popularity
    best_score = 0
    best_key = None
    best_pop = -1
    for key in _SORTED_KEYS:
        score = SequenceMatcher(None, item_lower, key).ratio()
        pop = MENU[key].get("popularity", 0)
        if score > best_score or (score == best_score and pop > best_pop):
            best_score = score
            best_key = key
            best_pop = pop

    if best_score >= 0.7 and best_key:
        m = MENU[best_key]
        return {
            "valid": True,
            "item_key": best_key,
            "price": m["price"],
            "audio_id": m["audio_id"],
            "corrected_from": item_lower,
        }

    # 4. No match — collect suggestions for clarification
    suggestions = []
    for key in _SORTED_KEYS:
        if any(word in key for word in item_lower.split() if len(word) >= 3):
            suggestions.append(key)
        if len(suggestions) >= 5:
            break

    return {
        "valid": False,
        "item_key": None,
        "original": item_lower,
        "suggestions": suggestions,
        "reason": "not found in menu",
    }


def _find_suggested_alternative(item_key: str, invalid_modifier: str) -> str | None:
    """Suggest a real MENU item that combines the stripped modifier word.

    When a customer says e.g. "mee goreng basah" we strip "basah" (invalid
    for noodle items), but they likely meant "kuey teow goreng basah" or
    another sibling item whose name actually contains the word. Prefers
    same-category items; ties broken by popularity.
    """
    mod = (invalid_modifier or "").lower().strip()
    if not mod or item_key not in MENU:
        return None
    item_category = MENU[item_key].get("category", "")
    candidates = []
    for name, meta in MENU.items():
        if name == item_key:
            continue
        if mod in name.split():
            same_cat = meta.get("category", "") == item_category
            candidates.append((same_cat, meta.get("popularity", 0), name))
    if not candidates:
        return None
    # Sort: same-category first (True > False), then higher popularity
    candidates.sort(reverse=True)
    return candidates[0][2]


def validate_order_items(extracted_items: list) -> dict:
    """
    Validate a full list of extracted items from DeepSeek/Qwen.

    Args:
        extracted_items: list of dicts from LLM, each with:
            {"matched_item": str, "quantity": int, "confidence": float, "modifiers": list}

    Returns:
        {
            "valid_items": [
                {
                    "item_key": "roti canai",
                    "quantity": 2,
                    "price": 2.00,
                    "audio_id": "0051",
                    "modifiers": ["garing"],
                    "stripped_modifiers": [],
                    "corrected_from": None
                }
            ],
            "invalid_items": [
                {
                    "original": "pizza hawaii",
                    "quantity": 1,
                    "reason": "not found in menu",
                    "suggestions": [...]
                }
            ],
            "modifier_warnings": [
                {"item": "mee goreng", "modifier": "basah",
                 "reason": "not allowed for noodle items",
                 "action": "stripped",
                 "suggested_alternative": "kuey teow goreng basah"}
            ],
            "suggested_alternatives": [
                {"item": "mee goreng", "invalid_modifier": "basah",
                 "alternative": "kuey teow goreng basah"}
            ],
            "needs_clarification": bool,
            "all_valid": bool
        }

    Policy (Apr 2026): an invalid modifier on an otherwise-valid item is
    STRIPPED, not rejected — the order proceeds to the kitchen without
    the bad modifier. Each strip is logged and surfaced via
    `modifier_warnings` and `suggested_alternatives` for audit and
    optional frontend re-prompt.
    """
    valid_items = []
    invalid_items = []
    modifier_warnings = []
    suggested_alternatives = []

    for item in extracted_items:
        item_name = item.get("matched_item", "").strip()
        quantity = item.get("quantity", 1)
        modifiers = item.get("modifiers", [])
        confidence = item.get("confidence", 0)

        if not item_name:
            continue

        # Validate the menu item
        result = validate_menu_item(item_name)

        if result["valid"]:
            # Validate modifiers — strip invalid ones, keep the item
            validated_mods = []
            stripped_mods = []
            for mod in modifiers:
                mod_result = validate_modifier(result["item_key"], mod)
                if mod_result["valid"]:
                    validated_mods.append(mod_result["modifier"])
                else:
                    stripped_mods.append(mod)
                    alt = _find_suggested_alternative(result["item_key"], mod)
                    print(
                        f"[Validator] Stripped invalid modifier '{mod}' "
                        f"from '{result['item_key']}'"
                        + (f" (suggested alternative: '{alt}')" if alt else "")
                    )
                    warning = {
                        "item": result["item_key"],
                        "modifier": mod,
                        "reason": mod_result["reason"],
                        "action": "stripped",
                    }
                    if alt:
                        warning["suggested_alternative"] = alt
                        suggested_alternatives.append({
                            "item": result["item_key"],
                            "invalid_modifier": mod,
                            "alternative": alt,
                        })
                    modifier_warnings.append(warning)

            valid_items.append({
                "item_key": result["item_key"],
                "quantity": quantity,
                "price": result["price"],
                "audio_id": result["audio_id"],
                "modifiers": validated_mods,
                "stripped_modifiers": stripped_mods,
                "corrected_from": result.get("corrected_from"),
            })
        else:
            invalid_items.append({
                "original": item_name,
                "quantity": quantity,
                "reason": result["reason"],
                "suggestions": result.get("suggestions", []),
            })

    needs_clarification = len(invalid_items) > 0
    all_valid = len(invalid_items) == 0 and len(valid_items) > 0

    return {
        "valid_items": valid_items,
        "invalid_items": invalid_items,
        "modifier_warnings": modifier_warnings,
        "suggested_alternatives": suggested_alternatives,
        "needs_clarification": needs_clarification,
        "all_valid": all_valid,
    }


# ================================================================
# ORDER LOGGING
# ================================================================

_LOG_DIR = "logs"
_LOG_FILE = os.path.join(_LOG_DIR, "order_log.jsonl")


def log_order_pipeline(
    table_number: str,
    whisper_transcript: str,
    deepseek_raw: str,
    deepseek_parsed: list | None,
    validated_result: dict,
    final_order: list,
    pipeline: str,
    qwen_reply: str = "",
):
    """
    Log the full order pipeline for observability.
    Each log entry is one JSONL line in logs/order_log.jsonl.
    """
    os.makedirs(_LOG_DIR, exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "table": table_number,
        "pipeline": pipeline,
        "whisper_transcript": whisper_transcript,
        "deepseek_raw": deepseek_raw,
        "deepseek_parsed": deepseek_parsed,
        "validation": {
            "valid_items": validated_result.get("valid_items", []),
            "invalid_items": validated_result.get("invalid_items", []),
            "modifier_warnings": validated_result.get("modifier_warnings", []),
            "suggested_alternatives": validated_result.get("suggested_alternatives", []),
            "needs_clarification": validated_result.get("needs_clarification", False),
        },
        "final_order": final_order,
        "aisha_reply": qwen_reply,
    }

    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"[OrderLog] Logged order for table {table_number}")
    except Exception as e:
        print(f"[OrderLog] Failed to write log: {e}")


def get_recent_logs(limit: int = 50) -> list:
    """Read recent order logs for review."""
    if not os.path.exists(_LOG_FILE):
        return []

    entries = []
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        print(f"[OrderLog] Failed to read log: {e}")
        return []

    return entries[-limit:]
