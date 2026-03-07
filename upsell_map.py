"""
Aisha Pre-Recorded Upsell Audio Map
====================================
Maps menu item names to pre-recorded upsell audio files (UP_001.mp3 – UP_048.mp3).
Each item can have one or more upsell audio clips; one is picked at random during
the voice chat flow.

Audio files live in: static/audio/wavs/
"""

import random

# Menu item → list of upsell audio IDs
UPSELL_AUDIO_MAP = {
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
}

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
