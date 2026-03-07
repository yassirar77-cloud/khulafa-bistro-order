"""
Aisha Pre-Recorded Upsell Audio Map
====================================
Maps menu item names to pre-recorded upsell audio files (UP_001.mp3 – UP_048.mp3).
Each item can have one or more upsell audio clips; one is picked at random during
the voice chat flow.

Audio files live in: static/audio/wavs/
"""

import random

# Audio ID → sentence text (what each pre-recorded clip says)
UPSELL_AUDIO_TEXT = {
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
}

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
