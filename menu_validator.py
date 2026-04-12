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
    item_lower = item_name.lower().strip()

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

    # 3. Fuzzy match using SequenceMatcher
    best_score = 0
    best_key = None
    for key in _SORTED_KEYS:
        score = SequenceMatcher(None, item_lower, key).ratio()
        if score > best_score:
            best_score = score
            best_key = key

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
                {"item": "roti canai", "modifier": "kurang manis", "reason": "not allowed for roti items"}
            ],
            "needs_clarification": bool,
            "all_valid": bool
        }
    """
    valid_items = []
    invalid_items = []
    modifier_warnings = []

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
            # Validate modifiers
            validated_mods = []
            for mod in modifiers:
                mod_result = validate_modifier(result["item_key"], mod)
                if mod_result["valid"]:
                    validated_mods.append(mod_result["modifier"])
                else:
                    modifier_warnings.append({
                        "item": result["item_key"],
                        "modifier": mod,
                        "reason": mod_result["reason"],
                    })

            valid_items.append({
                "item_key": result["item_key"],
                "quantity": quantity,
                "price": result["price"],
                "audio_id": result["audio_id"],
                "modifiers": validated_mods,
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
