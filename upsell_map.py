"""
Aisha Pre-Recorded Upsell Audio Map
====================================
Maps menu item names to pre-recorded upsell audio files (UP_001.mp3 – UP_112.mp3).
Each item can have one or more upsell audio clips; one is picked at random during
the voice chat flow.

Audio files live in: static/audio/wavs/

UP_001–UP_048: Batch 1 (food upsells)
UP_049–UP_108: Batch 2 (drink/combo upsells)
UP_109–UP_112: General responses (accept/reject/tak nak/cukup)
"""

import random

# Audio ID → sentence text (what each pre-recorded clip says)
UPSELL_AUDIO_TEXT = {
    # ── Batch 1: Food upsells (UP_001–UP_048) ──
    "UP_001": "Roti Canai satu!",
    "UP_002": "Nak try Roti Telur? Lagi sedap!",
    "UP_003": "Roti Canai Telur satu! Nak tambah Roti Bom? Lagi power!",
    "UP_004": "Roti Sardin satu! Nak try Roti Sardin Cheese? Lagi sedap!",
    "UP_005": "Roti Biasa satu! Nak upgrade Roti Telur? Lagi best!",
    "UP_006": "Capati Biasa satu! Nak try Capati Telur? Lagi sedap!",
    "UP_007": "Capati satu! Nak upgrade Capati Special? Lagi power!",
    "UP_008": "Capati Telur satu! Nak tambah dal? Sedap dimakan sama!",
    "UP_009": "Naan Biasa satu!",
    "UP_010": "Nak try Naan Cheese? Lagi sedap tau!",
    "UP_011": "Naan Cheese satu! Nak try Naan Cheese Garlic? Lagi power!",
    "UP_012": "Naan Garlic satu! Nak upgrade Naan Cheese Garlic? Lagi best!",
    "UP_013": "Naan Cheese Garlic satu! Nak tambah Naan Mozzerella? Lagi sedap!",
    "UP_014": "Naan Butter satu!",
    "UP_015": "Naan Mozzerella satu! Nak tambah minuman? Teh Tarik best!",
    "UP_016": "Chappathi Biasa satu! Nak try Chappathi Telur? Lagi sedap!",
    "UP_017": "Chappathi satu! Nak upgrade Chappathi Special? Lagi power!",
    "UP_018": "Chappathi Telur satu!",
    "UP_019": "Idli satu! Nak tambah sambar? Sedap dimakan sama!",
    "UP_020": "Appam satu! Nak try Appam Balik? Lagi sedap!",
    "UP_021": "Poori satu! Nak tambah dal? Memang best dimakan sama!",
    "UP_022": "Nasi Ayam satu!",
    "UP_023": "Nak try Nasi Ayam Bawang? Lagi sedap tau!",
    "UP_024": "Nasi Ayam Bawang satu! Nak tambah Ayam Goreng? Lagi puas!",
    "UP_025": "Nasi Putih satu! Nak tambah lauk? Ayam Goreng best!",
    "UP_026": "Briyani Ayam satu!",
    "UP_027": "Briyani Ayam Bawang satu!",
    "UP_028": "Briyani Kosong satu! Nak tambah Ayam Goreng atau Kambing? Lagi puas makan!",
    "UP_029": "Briyani Telur satu! Nak upgrade Briyani Ayam? Lagi sedap!",
    "UP_030": "Briyani Kambing satu! Nak tambah Naan? Sedap dimakan sama!",
    "UP_031": "Briyani Daging satu! Nak try Briyani Kambing? Lagi power!",
    "UP_032": "Nak try Briyani Ayam Bawang Set? Lagi berbaloi!",
    "UP_033": "Nasi Goreng Biasa satu! Nak upgrade Nasi Goreng Ayam? Lagi sedap!",
    "UP_034": "Nasi Goreng satu!",
    "UP_035": "Nasi Goreng Kampung satu! Nak try Nasi Goreng Seafood? Lagi power!",
    "UP_036": "Nak tambah telur mata? Lagi sedap!",
    "UP_037": "Nasi Goreng Ayam satu! Nak try Nasi Goreng Seafood? Lagi best!",
    "UP_038": "Nasi Goreng Cina satu! Nak tambah Sup? Sedap dimakan sama!",
    "UP_039": "Nasi Goreng Mamak satu!",
    "UP_040": "Mee Goreng satu! Nak try Mee Goreng Daging? Lagi sedap!",
    "UP_041": "Maggi Goreng satu!",
    "UP_042": "Nak try Maggi Goreng Kambing? Memang power!",
    "UP_043": "Kuetiau Goreng satu! Nak try Kuetiau Goreng Daging? Lagi sedap!",
    "UP_044": "Mihun Goreng satu! Nak tambah telur mata? Lagi best!",
    "UP_045": "Tomyam Ayam satu! Nak try Tomyam Seafood? Lagi power!",
    "UP_046": "Chicken Chop satu!",
    "UP_047": "Nak tambah Potato Wedges? Sedap dimakan sama!",
    "UP_048": "Potato Wedges satu! Nak tambah minuman? Milo Ais best!",
    # ── Batch 2: Drink/combo upsells (UP_049–UP_108) ──
    "UP_049": "Nasi Ayam Sayur! Nak upgrade Nasi Ayam Rendang Sayur? Lagi sedap!",
    "UP_050": "Nasi Putih Ayam Rempah! Nak tambah sayur? Lagi sihat!",
    "UP_051": "Briyani Sayur! Nak try Briyani Ayam Sayur? Lagi puas!",
    "UP_052": "Briyani Ikan! Nak ambil Briyani Ikan Set? Lagi berbaloi!",
    "UP_053": "Sup Ayam! Nak try Sup Daging? Lagi power!",
    "UP_054": "Tomyam! Nak upgrade Tomyam Seafood? Lagi best!",
    "UP_055": "Fish and Chips! Nak try Chicken Maryland? Lagi sedap!",
    "UP_056": "Teh Tarik! Nak upgrade Teh Special? Lagi sedap!",
    "UP_057": "Teh Tarik! Nak ambil Teh Besar? Lagi puas!",
    "UP_058": "Teh Ais! Nak upgrade Teh Ais Jumbo? Lagi puas!",
    "UP_059": "Teh O Ais! Nak ambil Jumbo? Lagi berbaloi!",
    "UP_060": "Teh O Ais! Nak try Teh O Limau Ais? Lagi segar!",
    "UP_061": "Teh O Limau Ais! Nak ambil Jumbo? Lagi puas!",
    "UP_062": "Teh Biasa! Nak try Tea Masala? Lagi special!",
    "UP_063": "Teh O! Nak try Teh O Halia? Lagi hangat sedap!",
    "UP_064": "Teh C! Nak ambil Teh C Besar? Lagi puas!",
    "UP_065": "Teh Halia! Nak ambil Teh Halia Besar? Lagi berbaloi!",
    "UP_066": "Teh Tarik! Nak try Teh Special Big? Paling best!",
    "UP_067": "Kopi! Nak try Kopi Jantan? Lagi power!",
    "UP_068": "Kopi O! Nak try Kopi O Halia? Lagi hangat sedap!",
    "UP_069": "Kopi Ais! Nak ambil Jumbo Kopi Ais? Lagi puas!",
    "UP_070": "Kopi O Ais! Nak ambil Jumbo Kopi O Ais? Lagi berbaloi!",
    "UP_071": "Kopi! Nak try Bru Coffee? Lagi premium!",
    "UP_072": "Kopi Jantan! Nak try Kopi Radix? Lagi power!",
    "UP_073": "Milo! Nak try Milo Ais Tabur? Lagi sedap!",
    "UP_074": "Milo Ais! Nak upgrade Milo Kow Ais? Lagi pekat sedap!",
    "UP_075": "Milo Ais! Nak ambil Milo Besar? Lagi puas!",
    "UP_076": "Milo! Nak try Milo Susu Lembu? Lagi creamy!",
    "UP_077": "Nescafe! Nak try Neslo? Lagi sedap!",
    "UP_078": "Nescafe Ais! Nak ambil Nescafe Besar? Lagi puas!",
    "UP_079": "Nescafe C! Nak ambil Nescafe C Besar? Lagi berbaloi!",
    "UP_080": "Nescafe! Nak try Nescafe Susu Lembu? Lagi creamy!",
    "UP_081": "Horlicks! Nak ambil Horlicks Ais Jumbo? Lagi puas!",
    "UP_082": "Horlicks! Nak ambil Horlicks Besar? Lagi berbaloi!",
    "UP_083": "Susu Lembu! Nak try Susu Halia? Lagi hangat sedap!",
    "UP_084": "Cham Tarik! Nak try Three Layer Tea? Lagi special!",
    "UP_085": "Tongkat Ali! Nak try Susukambing Higoat? Lagi power!",
    "UP_086": "Sirap Ais! Nak try Sirap Bandung Ais? Lagi sedap!",
    "UP_087": "Sirap Ais! Nak ambil Jumbo? Lagi puas!",
    "UP_088": "Sirap Bandung! Nak try Sirap Bandung Cincau Ais? Lagi best!",
    "UP_089": "Sirap Bandung Ais! Nak ambil Jumbo? Lagi berbaloi!",
    "UP_090": "Sirap Limau! Nak ambil Sirap Limau Ais Jumbo? Lagi puas!",
    "UP_091": "Sirap Bandung! Nak try Sirap Bandung Lychee Ais? Lagi segar!",
    "UP_092": "Barli Ais! Nak try Barli Lemon Ais? Lagi segar!",
    "UP_093": "Barli Ais! Nak ambil Jumbo? Lagi puas!",
    "UP_094": "Barli Panas! Nak try Barli Susu Panas? Lagi sedap!",
    "UP_095": "Barli Lemon! Nak try Barli Susu? Lagi creamy!",
    "UP_096": "Tembikai Juice! Nak try Tembikai Lychee? Lagi segar!",
    "UP_097": "Tembikai Juice! Nak try Tembikai Susu? Lagi creamy!",
    "UP_098": "Orange Juice! Nak upgrade Fresh Orange? Lagi segar!",
    "UP_099": "Apple Juice! Nak try Apple Carrot? Lagi sihat!",
    "UP_100": "Carrot Juice! Nak try Carrot Susu? Lagi creamy!",
    "UP_101": "Limau Ais! Nak ambil Limau Ais Jumbo? Lagi puas!",
    "UP_102": "Lemon Ais! Nak ambil Lemon Ais Jumbo? Lagi berbaloi!",
    # ── Combo cross-sell: food without drink (UP_103–UP_108) ──
    "UP_103": "Roti Canai! Nak tambah Teh Tarik? Memang combo best!",
    "UP_104": "Nasi Goreng! Nak tambah Teh O Ais? Sedap diminum sama!",
    "UP_105": "Briyani! Nak tambah Sirap Bandung Ais? Memang padan!",
    "UP_106": "Maggi Goreng! Nak tambah Milo Ais? Combo favourite ramai!",
    "UP_107": "Naan! Nak tambah Teh Tarik? Paling best diminum sama!",
    "UP_108": "Western Food! Nak tambah Lemon Ais? Segar dan sedap!",
    # ── General responses (UP_109–UP_112) ──
    "UP_109": "Okay terima kasih! Ditambah ya!",
    "UP_110": "Okay takpe! Ada lagi nak order?",
    "UP_111": "Okay takpe, tak nak takpe! Ada lagi?",
    "UP_112": "Baik, confirm order! Terima kasih!",
}

# Menu item → list of upsell audio IDs
UPSELL_AUDIO_MAP = {
    # ── Batch 1: Food upsells ──
    "Roti Canai": ["UP_001", "UP_002"],
    "Roti Canai Telur": ["UP_003"],
    "Roti Sardin": ["UP_004"],
    "Roti Biasa": ["UP_005"],
    "Capati Biasa": ["UP_006"],
    "Capati": ["UP_007"],
    "Capati Telur": ["UP_008"],
    "Naan Biasa": ["UP_009", "UP_010"],
    "Naan Cheese": ["UP_011"],
    "Naan Garlic": ["UP_012"],
    "Naan Cheese Garlic": ["UP_013"],
    "Naan Butter": ["UP_014"],
    "Naan Mozzerella": ["UP_015"],
    "Chappathi Biasa": ["UP_016"],
    "Chappathi": ["UP_017"],
    "Chappathi Telur": ["UP_018"],
    "Idli": ["UP_019"],
    "Appam": ["UP_020"],
    "Poori": ["UP_021"],
    "Nasi Ayam": ["UP_022", "UP_023"],
    "Nasi Ayam Bawang": ["UP_024"],
    "Nasi Putih": ["UP_025"],
    "Briyani Ayam": ["UP_026"],
    "Briyani Ayam Bawang": ["UP_027", "UP_032"],
    "Briyani Kosong": ["UP_028"],
    "Briyani Telur": ["UP_029"],
    "Briyani Kambing": ["UP_030"],
    "Briyani Daging": ["UP_031"],
    "Nasi Goreng Biasa": ["UP_033"],
    "Nasi Goreng": ["UP_034", "UP_036"],
    "Nasi Goreng Kampung": ["UP_035"],
    "Nasi Goreng Ayam": ["UP_037"],
    "Nasi Goreng Cina": ["UP_038"],
    "Nasi Goreng Mamak": ["UP_039"],
    "Mee Goreng": ["UP_040"],
    "Maggi Goreng": ["UP_041", "UP_042"],
    "Kuetiau Goreng": ["UP_043"],
    "Mihun Goreng": ["UP_044"],
    "Tomyam Ayam": ["UP_045"],
    "Chicken Chop": ["UP_046", "UP_047"],
    "Potato Wedges": ["UP_048"],
    # ── Batch 2: Drink/combo upsells ──
    "Nasi Ayam Sayur": ["UP_049"],
    "Nasi Putih Ayam Rempah": ["UP_050"],
    "Briyani Sayur": ["UP_051"],
    "Briyani Ikan": ["UP_052"],
    "Sup Ayam": ["UP_053"],
    "Tomyam": ["UP_054"],
    "Fish and Chips": ["UP_055"],
    "Teh Tarik": ["UP_056", "UP_057", "UP_066"],
    "Teh Ais": ["UP_058"],
    "Teh O Ais": ["UP_059", "UP_060"],
    "Teh O Limau Ais": ["UP_061"],
    "Teh Biasa": ["UP_062"],
    "Teh O": ["UP_063"],
    "Teh C": ["UP_064"],
    "Teh Halia": ["UP_065"],
    "Kopi": ["UP_067", "UP_071"],
    "Kopi O": ["UP_068"],
    "Kopi Ais": ["UP_069"],
    "Kopi O Ais": ["UP_070"],
    "Kopi Jantan": ["UP_072"],
    "Milo": ["UP_073", "UP_076"],
    "Milo Ais": ["UP_074", "UP_075"],
    "Nescafe": ["UP_077", "UP_080"],
    "Nescafe Ais": ["UP_078"],
    "Nescafe C": ["UP_079"],
    "Horlicks": ["UP_081", "UP_082"],
    "Susu Lembu": ["UP_083"],
    "Cham Tarik": ["UP_084"],
    "Tongkat Ali": ["UP_085"],
    "Sirap Ais": ["UP_086", "UP_087"],
    "Sirap Bandung": ["UP_088", "UP_091"],
    "Sirap Bandung Ais": ["UP_089"],
    "Sirap Limau": ["UP_090"],
    "Barli Ais": ["UP_092", "UP_093"],
    "Barli Panas": ["UP_094"],
    "Barli Lemon": ["UP_095"],
    "Tembikai Juice": ["UP_096", "UP_097"],
    "Orange Juice": ["UP_098"],
    "Apple Juice": ["UP_099"],
    "Carrot Juice": ["UP_100"],
    "Limau Ais": ["UP_101"],
    "Lemon Ais": ["UP_102"],
}

# Combo cross-sell: food category → drink suggestion audio
# Used when customer orders food but no drink yet
COMBO_CROSS_SELL = {
    "Roti Canai": "UP_103",
    "Nasi Goreng": "UP_104",
    "Briyani": "UP_105",
    "Maggi Goreng": "UP_106",
    "Naan": "UP_107",
    "Western Food": "UP_108",
}

# General response audio IDs
GENERAL_RESPONSES = {
    "accept": "UP_109",   # Customer accepts upsell
    "reject": "UP_110",   # Customer rejects upsell
    "tak_nak": "UP_111",  # Customer says tak nak
    "cukup": "UP_112",    # Customer says cukup/confirm
}

# Food categories for combo cross-sell matching
_FOOD_CATEGORIES = {
    "roti canai": ["roti canai", "roti telur", "roti sardin", "roti biasa", "roti bom",
                   "roti special", "roti jantan", "roti cheese", "roti bawang", "roti planta",
                   "roti khawin", "roti tissue", "roti pisang", "roti milo", "roti kaya",
                   "roti bakar"],
    "nasi goreng": ["nasi goreng", "nasi goreng biasa", "nasi goreng ayam", "nasi goreng kampung",
                    "nasi goreng mamak", "nasi goreng seafood", "nasi goreng cina",
                    "nasi goreng pattaya", "nasi goreng usa"],
    "briyani": ["briyani", "briyani ayam", "briyani ayam bawang", "briyani kambing",
                "briyani daging", "briyani telur", "briyani kosong", "briyani ikan",
                "briyani sayur", "briyani lamb shank"],
    "maggi goreng": ["maggi goreng", "maggi goreng mamak", "maggi goreng ayam",
                     "maggi goreng daging", "maggi goreng kambing", "maggi goreng telur mata",
                     "maggi goreng basah"],
    "naan": ["naan", "naan biasa", "naan cheese", "naan garlic", "naan butter",
             "naan cheese garlic", "naan mozzerella", "naan mumtaj", "naan tajmahal"],
    "western food": ["chicken chop", "lamb chop", "fish and chips", "chicken maryland",
                     "lamb shank", "potato wedges"],
}

# Drink keywords for detecting if customer already has a drink
_DRINK_KEYWORDS = [
    "teh", "kopi", "milo", "nescafe", "horlicks", "susu", "sirap", "barli",
    "juice", "limau", "lemon", "air", "cham", "tongkat", "neslo", "bandung",
    "orange", "apple", "carrot", "tembikai", "bru coffee",
]

# Build a lowercase lookup for case-insensitive matching
_UPSELL_AUDIO_LOOKUP: dict[str, list[str]] = {
    k.lower(): v for k, v in UPSELL_AUDIO_MAP.items()
}


def get_upsell_audio(item_name: str) -> str | None:
    """
    Given a menu item name, return a randomly chosen upsell audio ID
    (e.g. "UP_001") or None if no upsell audio exists for that item.
    """
    key = item_name.strip().lower()
    candidates = _UPSELL_AUDIO_LOOKUP.get(key)
    if candidates:
        return random.choice(candidates)
    return None


def get_upsell_audio_path(item_name: str) -> str | None:
    """
    Return the full audio path (e.g. "/audio/wavs/UP_001.mp3") or None.
    """
    audio_id = get_upsell_audio(item_name)
    if audio_id:
        return f"/audio/wavs/{audio_id}.mp3"
    return None


def get_upsell_audio_info(item_name: str) -> dict | None:
    """
    Return audio ID, path, and subtitle text for an upsell clip, or None.
    """
    audio_id = get_upsell_audio(item_name)
    if audio_id:
        return {
            "audio_id": audio_id,
            "audio_path": f"/audio/wavs/{audio_id}.mp3",
            "text": UPSELL_AUDIO_TEXT.get(audio_id, ""),
        }
    return None


def _has_drink_in_order(order: list[dict]) -> bool:
    """Check if the current order already contains a drink."""
    for item in order:
        name = item.get("name", "").lower()
        for kw in _DRINK_KEYWORDS:
            if kw in name:
                return True
    return False


def _get_food_category(item_name: str) -> str | None:
    """Return the food category key for combo cross-sell, or None."""
    name_lower = item_name.strip().lower()
    for category, items in _FOOD_CATEGORIES.items():
        for food in items:
            if name_lower == food or name_lower.startswith(food):
                return category
    return None


def get_combo_cross_sell(item_name: str, current_order: list[dict]) -> dict | None:
    """
    If customer ordered food but no drink, suggest a drink combo.
    Returns dict with audio_id, audio_path, text, suggested_drink or None.
    """
    if _has_drink_in_order(current_order):
        return None

    category = _get_food_category(item_name)
    if not category:
        return None

    combo_key = category.title()
    if combo_key == "Western Food":
        combo_key = "Western Food"
    audio_id = COMBO_CROSS_SELL.get(combo_key)
    if audio_id:
        return {
            "audio_id": audio_id,
            "audio_path": f"/audio/wavs/{audio_id}.mp3",
            "text": UPSELL_AUDIO_TEXT.get(audio_id, ""),
            "type": "combo_cross_sell",
        }
    return None


def get_general_response_audio(response_type: str) -> dict | None:
    """
    Get audio for general upsell responses.
    response_type: 'accept', 'reject', 'tak_nak', or 'cukup'
    """
    audio_id = GENERAL_RESPONSES.get(response_type)
    if audio_id:
        return {
            "audio_id": audio_id,
            "audio_path": f"/audio/wavs/{audio_id}.mp3",
            "text": UPSELL_AUDIO_TEXT.get(audio_id, ""),
        }
    return None
