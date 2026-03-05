"""
Aisha Upsell Engine — Profit-Driven Recommendation System
==========================================================
When a customer orders a basic item, Aisha recommends the UPGRADED/PREMIUM
version of the SAME item that costs more. Strategic upselling, not random pairings.

Rules:
- Always suggest the MORE EXPENSIVE version of what they ordered
- Keep it natural: "sedap jugak", "nak try?", "lagi best"
- Only 1 upsell attempt per item, accept "no" gracefully
- If customer already orders premium, suggest add-on drinks/sides
- Sort recommendations by HIGHEST PRICE MARGIN first

Integrates with ElevenLabs TTS for voice upselling.
"""

import os
import httpx
from order_engine import MENU

# ------------------------------------------------------------------ #
#  UPSELL MAP — built from the actual Khulafa menu                    #
#  Format: "basic_item" → [(upsell_item, margin, suggestion_text)]    #
#  Sorted by highest margin first within each entry                   #
# ------------------------------------------------------------------ #

# Each entry: (upsell_item_key, casual_malay_suggestion)
# Margin is computed automatically from MENU prices.

_RAW_UPSELL_MAP = {
    # === ROTI ===
    "roti canai": [
        ("roti special", "Roti Special lagi sedap! Nak try?"),
        ("roti jantan", "Roti Jantan lagi power! Nak try?"),
        ("roti telur", "Roti Telur pun best jugak! Nak?"),
    ],
    "roti telur": [
        ("roti telur cheese", "Roti Telur Cheese lagi sedap! Nak try?"),
        ("roti telur bawang", "Roti Telur Bawang pun best! Nak?"),
    ],
    "roti boom": [
        ("roti boom kaya", "Roti Boom Kaya lagi best! Nak try?"),
    ],
    "roti pisang": [
        ("roti pisang cheese", "Roti Pisang Cheese lagi sedap! Nak try?"),
    ],
    "roti cheese": [
        ("roti telur cheese", "Roti Telur Cheese lagi puas! Nak try?"),
    ],
    "roti bakar": [
        ("roti bakar cheese", "Roti Bakar Cheese lagi best! Nak try?"),
        ("roti bakar kaya", "Roti Bakar Kaya pun sedap! Nak?"),
    ],
    "roti special": [
        ("roti special double", "Roti Special Double lagi puas! Nak try?"),
    ],
    "roti bawang": [
        ("roti jantan", "Roti Jantan lagi power! Nak try?"),
    ],
    "roti planta": [
        ("roti cheese", "Roti Cheese lagi sedap! Nak try?"),
    ],
    "roti khawin": [
        ("roti jantan", "Roti Jantan lagi best! Nak try?"),
    ],

    # === NAAN ===
    "naan biasa": [
        ("naan mumtaj", "Naan Mumtaj lagi power! Nak try?"),
        ("naan cheese", "Naan Cheese lagi sedap! Nak try?"),
        ("naan butter garlic", "Naan Butter Garlic pun best! Nak?"),
    ],
    "naan butter": [
        ("naan cheese", "Naan Cheese lagi sedap! Nak try?"),
        ("naan butter garlic", "Naan Butter Garlic pun best! Nak?"),
    ],
    "naan garlic": [
        ("naan cheese garlic", "Naan Cheese Garlic lagi power! Nak try?"),
    ],
    "naan cheese": [
        ("naan cheese double", "Naan Cheese Double lagi puas! Nak try?"),
        ("naan mozzerella cheese", "Naan Mozzerella lagi sedap! Nak try?"),
    ],
    "naan butter garlic": [
        ("naan cheese garlic", "Naan Cheese Garlic lagi sedap! Nak try?"),
    ],
    "naan cheese garlic": [
        ("naan mozzerella cheese", "Naan Mozzerella Cheese lagi best! Nak try?"),
    ],

    # === NASI ===
    "nasi putih": [
        ("nasi ayam", "Nasi Ayam lagi puas! Nak try?"),
        ("nasi daging", "Nasi Daging pun power! Nak try?"),
    ],
    "nasi ayam": [
        ("nasi ayam rendang", "Nasi Ayam Rendang lagi sedap! Nak try?"),
        ("nasi ayam bawang", "Nasi Ayam Bawang pun best! Nak try?"),
    ],
    "nasi ayam sayur": [
        ("nasi ayam bawang sayur", "Nasi Ayam Bawang Sayur lagi puas! Nak try?"),
    ],
    "nasi ayam bawang": [
        ("nasi ayam bawang sayur", "Tambah sayur lagi sihat! Nak try?"),
    ],

    # === BRIYANI ===
    "briyani ayam": [
        ("briyani ayam goreng set", "Briyani Ayam Goreng Set lagi puas! Nak try?"),
        ("briyani ayam bawang", "Briyani Ayam Bawang lagi sedap! Nak try?"),
    ],
    "briyani ayam bawang": [
        ("briyani ayam bawang set", "Ambil set lagi berbaloi! Nak try?"),
    ],
    "briyani ayam goreng set": [
        ("briyani ayam bawang set", "Briyani Ayam Bawang Set lagi best! Nak try?"),
    ],
    "briyani kambing": [
        ("briyani kambing set", "Ambil set lagi puas! Nak try?"),
    ],
    "briyani daging set": [
        ("briyani kambing set", "Briyani Kambing Set lagi power! Nak try?"),
    ],

    # === NASI GORENG ===
    "nasi goreng biasa": [
        ("nasi goreng seafood", "Nasi Goreng Seafood lagi power! Nak try?"),
        ("nasi goreng ayam", "Nasi Goreng Ayam pun sedap! Nak try?"),
        ("nasi goreng pattaya", "Nasi Goreng Pattaya pun best! Nak try?"),
    ],
    "nasi goreng kampung": [
        ("nasi goreng seafood", "Nasi Goreng Seafood lagi power! Nak try?"),
        ("nasi goreng ayam", "Nasi Goreng Ayam pun sedap jugak! Nak try?"),
    ],
    "nasi goreng mamak": [
        ("nasi goreng seafood", "Nasi Goreng Seafood lagi best! Nak try?"),
        ("nasi goreng ayam", "Nasi Goreng Ayam pun power! Nak try?"),
    ],
    "nasi goreng ayam": [
        ("nasi goreng seafood", "Nasi Goreng Seafood lagi power! Nak tukar?"),
    ],
    "nasi goreng pattaya": [
        ("nasi goreng seafood", "Nasi Goreng Seafood lagi best! Nak try?"),
    ],

    # === MAGGI ===
    "maggi goreng": [
        ("maggi goreng kambing", "Maggi Goreng Kambing lagi power! Nak try?"),
        ("maggi goreng daging", "Maggi Goreng Daging pun sedap! Nak try?"),
        ("maggi goreng ayam", "Maggi Goreng Ayam pun best jugak! Nak?"),
    ],
    "maggi goreng mamak": [
        ("maggi goreng kambing", "Maggi Goreng Kambing lagi power! Nak try?"),
        ("maggi goreng daging", "Maggi Goreng Daging pun sedap! Nak try?"),
    ],
    "maggi goreng basa": [
        ("maggi goreng daging", "Maggi Goreng Daging lagi sedap! Nak try?"),
        ("maggi goreng ayam", "Maggi Goreng Ayam pun best! Nak try?"),
    ],
    "maggi goreng ayam": [
        ("maggi goreng kambing", "Maggi Goreng Kambing lagi power! Nak tukar?"),
    ],
    "maggi goreng daging": [
        ("maggi goreng kambing", "Maggi Goreng Kambing lagi best! Nak tukar?"),
    ],
    "maggi sup": [
        ("maggi tomyam", "Maggi Tomyam lagi sedap! Nak try?"),
    ],
    "maggi goreng telur mata": [
        ("maggi goreng daging", "Maggi Goreng Daging lagi power! Nak try?"),
    ],

    # === MEE ===
    "mee goreng": [
        ("mee goreng daging", "Mee Goreng Daging lagi power! Nak try?"),
        ("mee goreng ayam", "Mee Goreng Ayam pun sedap! Nak try?"),
    ],
    "mee goreng mamak": [
        ("mee goreng seafood", "Mee Goreng Seafood lagi best! Nak try?"),
        ("mee goreng daging", "Mee Goreng Daging pun power! Nak try?"),
    ],
    "mee goreng ayam": [
        ("mee goreng seafood", "Mee Goreng Seafood lagi power! Nak tukar?"),
    ],
    "mee goreng daging": [
        ("mee goreng seafood", "Mee Goreng Seafood lagi best! Nak tukar?"),
    ],
    "mee goreng telur mata": [
        ("mee goreng daging", "Mee Goreng Daging lagi sedap! Nak try?"),
    ],

    # === BIHUN & KUEY TEOW ===
    "bihun goreng": [
        ("bihun goreng telur mata", "Bihun Goreng Telur Mata lagi sedap! Nak try?"),
    ],
    "bihun goreng mamak": [
        ("bihun goreng telur mata", "Bihun Goreng Telur Mata lagi best! Nak try?"),
    ],
    "kuey teow goreng": [
        ("kuey teow goreng basa", "Kuey Teow Goreng Basa lagi sedap! Nak try?"),
        ("kuey teow tomyam", "Kuey Teow Tomyam pun power! Nak try?"),
    ],
    "kuey teow goreng mamak": [
        ("kuey teow tomyam", "Kuey Teow Tomyam lagi best! Nak try?"),
    ],

    # === INDOMEE ===
    "indomee kosong": [
        ("indomee double", "Indomee Double lagi puas! Nak try?"),
        ("indomee goreng", "Indomee Goreng pun sedap! Nak try?"),
    ],
    "indomee goreng": [
        ("indomee double", "Indomee Double lagi puas! Nak try?"),
    ],

    # === MURTABAK ===
    "murtabak ayam": [
        ("murtabak kambing", "Murtabak Kambing lagi power! Nak try?"),
        ("murtabak daging", "Murtabak Daging pun sedap! Nak try?"),
    ],
    "murtabak daging": [
        ("murtabak kambing", "Murtabak Kambing lagi best! Nak try?"),
    ],

    # === LAUK ===
    "ayam goreng": [
        ("ayam tandoori", "Ayam Tandoori lagi power! Nak try?"),
        ("ayam rendang", "Ayam Rendang pun sedap! Nak try?"),
        ("ayam bawang", "Ayam Bawang pun best! Nak try?"),
    ],
    "ayam bawang": [
        ("ayam tandoori", "Ayam Tandoori lagi power! Nak try?"),
        ("ayam rendang", "Ayam Rendang pun best! Nak try?"),
    ],
    "ayam kari": [
        ("ayam tandoori", "Ayam Tandoori lagi sedap! Nak try?"),
        ("ayam rendang", "Ayam Rendang pun best jugak! Nak?"),
    ],

    # === DRINKS ===
    "teh tarik": [
        ("milo ais", "Milo Ais lagi sedap! Nak try?"),
        ("bandung ais", "Bandung Ais pun best! Nak try?"),
    ],
    "teh ais": [
        ("milo ais", "Milo Ais lagi sedap! Nak try?"),
        ("bandung ais", "Bandung Ais pun power! Nak try?"),
    ],
    "kopi panas": [
        ("kopi ais", "Kopi Ais lagi syok! Nak try?"),
    ],
    "sirap ais": [
        ("bandung ais", "Bandung Ais lagi sedap! Nak try?"),
        ("cincau", "Cincau pun syok! Nak try?"),
    ],
    "sirap panas": [
        ("bandung panas", "Bandung Panas lagi sedap! Nak try?"),
        ("bandung ais", "Bandung Ais pun syok! Nak try?"),
    ],
    "milo panas": [
        ("milo ais", "Milo Ais lagi syok! Nak try?"),
    ],
    "bandung": [
        ("bandung ais", "Bandung Ais lagi syok! Nak try?"),
    ],
    "bandung panas": [
        ("bandung ais", "Bandung Ais lagi syok! Nak try?"),
    ],
    "barli panas": [
        ("barli ais", "Barli Ais lagi syok! Nak try?"),
    ],
    "air kosong": [
        ("air mineral", "Air Mineral lagi best! Nak try?"),
    ],
}

# Add-on suggestions for premium items (already at top tier)
# When customer orders the best version, suggest drinks/sides instead
_ADDON_SUGGESTIONS = {
    "drinks": [
        ("milo ais", "Tambah Milo Ais? Sedap jugak!"),
        ("teh tarik", "Tambah Teh Tarik? Best!"),
        ("bandung ais", "Tambah Bandung Ais? Syok!"),
    ],
    "sides": [
        ("roti canai", "Tambah Roti Canai? Sedap dimakan sama!"),
        ("ayam goreng", "Tambah Ayam Goreng? Power!"),
    ],
}

# Items considered "premium" (no higher version exists in their family)
_PREMIUM_ITEMS = {
    "roti special double", "naan tajmahal", "naan mumtaj", "naan cheese double",
    "briyani lamb shank", "briyani kambing set", "briyani ayam bawang set",
    "nasi goreng seafood", "maggi goreng kambing", "mee goreng seafood",
    "murtabak kambing", "kambing mysur", "ayam tandoori",
    "indomee double", "chicken chop",
    "milo ais", "bandung ais", "longan", "cincau",
}


# ------------------------------------------------------------------ #
#  Computed UPSELL_MAP with margins                                    #
# ------------------------------------------------------------------ #

def _build_upsell_map():
    """
    Build the final upsell map with computed price margins.
    Each entry: item_key → [{"item": key, "price": X, "margin": Y, "text": "..."}]
    Sorted by highest margin first.
    """
    upsell_map = {}

    for base_item, upsells in _RAW_UPSELL_MAP.items():
        if base_item not in MENU:
            continue

        base_price = MENU[base_item]["price"]
        computed = []

        for upsell_key, suggestion_text in upsells:
            if upsell_key not in MENU:
                continue

            upsell_price = MENU[upsell_key]["price"]
            margin = upsell_price - base_price

            if margin <= 0:
                continue  # Only upsell to MORE expensive items

            computed.append({
                "item": upsell_key,
                "item_display": upsell_key.title(),
                "price": upsell_price,
                "margin": round(margin, 2),
                "text": suggestion_text,
            })

        # Sort by highest margin first (most profit)
        computed.sort(key=lambda x: -x["margin"])

        if computed:
            upsell_map[base_item] = computed

    return upsell_map


UPSELL_MAP = _build_upsell_map()


# ------------------------------------------------------------------ #
#  ElevenLabs TTS Integration                                         #
# ------------------------------------------------------------------ #

_elevenlabs_api_key = None
_elevenlabs_voice_id = None


def _get_elevenlabs_config():
    """Get ElevenLabs API config from environment."""
    global _elevenlabs_api_key, _elevenlabs_voice_id
    if _elevenlabs_api_key is None:
        _elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY", "")
        _elevenlabs_voice_id = os.getenv(
            "ELEVENLABS_VOICE_ID",
            "21m00Tcm4TlvDq8ikWAM"  # Default: Rachel voice
        )
    return _elevenlabs_api_key, _elevenlabs_voice_id


async def generate_upsell_audio(text: str) -> bytes | None:
    """
    Generate speech audio for an upsell suggestion using ElevenLabs TTS.

    Returns MP3 bytes or None if ElevenLabs is not configured.
    """
    api_key, voice_id = _get_elevenlabs_config()
    if not api_key:
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.4,  # Friendly, casual mamak style
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                return response.content
            print(f"[UpsellEngine] ElevenLabs error: {response.status_code}")
            return None
    except Exception as e:
        print(f"[UpsellEngine] ElevenLabs TTS error: {e}")
        return None


# ------------------------------------------------------------------ #
#  UpsellEngine class                                                  #
# ------------------------------------------------------------------ #

class UpsellEngine:
    """Profit-driven upsell recommendation engine for Aisha voice bot."""

    def __init__(self):
        # Track which items have already been upsold in this session
        # to enforce "only 1 upsell attempt per item" rule
        self._upsold_items: set[str] = set()

    def reset_session(self):
        """Reset upsell tracking for a new customer session."""
        self._upsold_items.clear()

    def get_upsell(self, item_name: str) -> dict | None:
        """
        Get the best upsell recommendation for an ordered item.

        Parameters
        ----------
        item_name : str
            The menu item the customer just ordered (lowercase key).

        Returns
        -------
        dict or None
            {
                "original": "maggi goreng",
                "original_price": 6.00,
                "upsell_item": "maggi goreng kambing",
                "upsell_display": "Maggi Goreng Kambing",
                "upsell_price": 13.00,
                "margin": 7.00,
                "suggestion_text": "Maggi Goreng Kambing lagi power! Nak try?",
                "type": "upgrade"
            }
        """
        key = item_name.strip().lower()

        # Rule: only 1 upsell attempt per item
        if key in self._upsold_items:
            return None

        self._upsold_items.add(key)

        # Check if item has direct upsells
        if key in UPSELL_MAP:
            best = UPSELL_MAP[key][0]  # Already sorted by highest margin
            return {
                "original": key,
                "original_price": MENU[key]["price"],
                "upsell_item": best["item"],
                "upsell_display": best["item_display"],
                "upsell_price": best["price"],
                "margin": best["margin"],
                "suggestion_text": best["text"],
                "type": "upgrade",
            }

        # If premium item, suggest add-on drink or side
        if key in _PREMIUM_ITEMS:
            return self._get_addon_suggestion(key)

        return None

    def get_all_upsells(self, item_name: str) -> list[dict]:
        """
        Get ALL upsell options for an item (for UI display).
        Does not affect the upsold tracking.
        """
        key = item_name.strip().lower()

        if key in UPSELL_MAP:
            base_price = MENU[key]["price"]
            return [
                {
                    "original": key,
                    "original_price": base_price,
                    "upsell_item": u["item"],
                    "upsell_display": u["item_display"],
                    "upsell_price": u["price"],
                    "margin": u["margin"],
                    "suggestion_text": u["text"],
                    "type": "upgrade",
                }
                for u in UPSELL_MAP[key]
            ]
        return []

    def accept_upsell(self, original_item: str, upsell_item: str) -> dict | None:
        """
        Customer accepted the upsell. Return the replacement item details.

        Returns the new item info from MENU or None if invalid.
        """
        key = upsell_item.strip().lower()
        if key in MENU:
            return {
                "name": key.title(),
                "price": MENU[key]["price"],
                "audio_id": MENU[key]["audio_id"],
                "replaced": original_item.strip().lower(),
            }
        return None

    def decline_upsell(self, item_name: str):
        """Customer declined — mark as upsold so we don't ask again."""
        self._upsold_items.add(item_name.strip().lower())

    def _get_addon_suggestion(self, premium_key: str) -> dict | None:
        """Suggest a drink or side add-on for premium items."""
        # Determine if food or drink based on MENU categories
        is_drink = premium_key in {
            "milo ais", "bandung ais", "longan", "cincau",
        }

        suggestions = _ADDON_SUGGESTIONS["sides" if is_drink else "drinks"]

        for addon_key, text in suggestions:
            if addon_key not in MENU:
                continue
            if addon_key in self._upsold_items:
                continue

            return {
                "original": premium_key,
                "original_price": MENU[premium_key]["price"],
                "upsell_item": addon_key,
                "upsell_display": addon_key.title(),
                "upsell_price": MENU[addon_key]["price"],
                "margin": MENU[addon_key]["price"],  # Full price since it's an add-on
                "suggestion_text": text,
                "type": "addon",
            }
        return None

    def get_upsell_stats(self) -> dict:
        """Return stats about the upsell map for debugging/admin."""
        total_items_with_upsells = len(UPSELL_MAP)
        total_upsell_options = sum(len(v) for v in UPSELL_MAP.values())
        avg_margin = 0
        if total_upsell_options > 0:
            all_margins = [
                u["margin"]
                for upsells in UPSELL_MAP.values()
                for u in upsells
            ]
            avg_margin = round(sum(all_margins) / len(all_margins), 2)

        top_margins = []
        for base_item, upsells in UPSELL_MAP.items():
            best = upsells[0]
            top_margins.append({
                "from": base_item.title(),
                "to": best["item_display"],
                "margin": best["margin"],
            })
        top_margins.sort(key=lambda x: -x["margin"])

        return {
            "total_items_with_upsells": total_items_with_upsells,
            "total_upsell_options": total_upsell_options,
            "average_margin_rm": avg_margin,
            "premium_items_count": len(_PREMIUM_ITEMS),
            "top_10_margins": top_margins[:10],
        }


# ------------------------------------------------------------------ #
#  Singleton accessor                                                  #
# ------------------------------------------------------------------ #

_upsell_instance = None


def get_upsell_engine() -> UpsellEngine:
    global _upsell_instance
    if _upsell_instance is None:
        _upsell_instance = UpsellEngine()
    return _upsell_instance
