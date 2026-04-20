"""
Rule-based ordering engine for Khulafa Bistro.
Zero API cost, instant response, always correct.
"""

from datetime import datetime
import re

# Malay number words → integers
MALAY_NUMBERS = {
    "satu": 1, "se": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
    "enam": 6, "tujuh": 7, "lapan": 8, "sembilan": 9, "sepuluh": 10,
}

# End-of-order phrases
END_PHRASES = [
    "tu je", "tu jer", "tu aje", "tu ajer",
    "itu je", "itu jer", "itu aje", "itu ajer",
    "itu sahaja", "itu saja",
    "cukup", "cukup lah", "cukuplah",
    "dah", "dah cukup", "dah lah",
    "habis", "habis dah",
    "sekian", "confirm", "konfem", "konfirm",
    "tak nak dah", "taknak dah", "takde dah",
    "sudah", "sudah cukup",
    "okay tu je", "ok tu je",
    "settle", "setel",
]

# Full menu: name -> (audio_id, price, popularity, category)
# Updated from Khulafa Bistro sales data 06-Apr-2026 (197 items merged)
MENU = {
    # === ROTI / NAAN / BREAD ===
    "roti canai susu":              ("0081", 3.00, 0, "bread"),
    "roti canai":                   ("0051", 1.50, 60, "bread"),
    "roti telur bawang":            ("0057", 3.00, 4, "bread"),
    "roti telur cheese":            ("0059", 4.50, 0, "bread"),
    "roti telur":                   ("0054", 2.50, 29, "bread"),
    "roti sardin":                  ("0060", 4.00, 8, "bread"),
    "roti khawin":                  ("0062", 4.00, 4, "bread"),
    "roti boom kaya":               ("0064", 3.50, 0, "bread"),
    "roti boom":                    ("0063", 2.50, 2, "bread"),
    "roti tissue":                  ("0065", 3.00, 0, "bread"),
    "roti pisang cheese":           ("0067", 4.50, 0, "bread"),
    "roti pisang":                  ("0066", 3.00, 1, "bread"),
    "roti planta":                  ("0069", 2.50, 4, "bread"),
    "roti cheese":                  ("0072", 3.20, 1, "bread"),
    "roti bawang":                  ("0073", 2.50, 0, "bread"),
    "roti jantan":                  ("0075", 4.00, 0, "bread"),
    "roti special double":          ("0080", 7.00, 0, "bread"),
    "roti special":                 ("0079", 5.00, 0, "bread"),
    "roti milo":                    ("0082", 3.50, 0, "bread"),
    "roti kaya":                    ("0083", 2.50, 1, "bread"),
    "roti bakar kaya":              ("0087", 3.50, 0, "bread"),
    "roti bakar cheese":            ("0089", 4.00, 0, "bread"),
    "roti bakar":                   ("0086", 2.50, 11, "bread"),
    "roti khulafa special":         ("", 4.50, 2, "bread"),
    "roti open":                    ("", 0.50, 1, "bread"),
    "roti tambal":                  ("", 2.50, 1, "bread"),
    "murtabak ayam":                ("0092", 9.00, 0, "bread"),
    "murtabak daging":              ("0093", 10.00, 0, "bread"),
    "murtabak kambing":             ("0094", 12.00, 0, "bread"),
    "capati kua sardin":            ("", 2.80, 7, "bread"),
    "chappathi a":                  ("", 2.30, 1, "bread"),
    "chappathi kua sardin a":       ("", 2.80, 4, "bread"),
    "thosai biasa":                 ("", 2.20, 9, "bread"),
    "thosai paper":                 ("", 3.20, 2, "bread"),
    "thosai telur":                 ("", 3.20, 1, "bread"),
    "tosai biasa a":                ("", 2.20, 4, "bread"),
    "tosai masala a":               ("", 4.00, 1, "bread"),

    # === NAAN ===
    "naan mozzerella cheese":       ("0112", 7.00, 17, "bread"),
    "naan cheese garlic":           ("0115", 5.50, 0, "bread"),
    "naan cheese double":           ("0120", 7.00, 0, "bread"),
    "naan cheese":                  ("0113", 5.00, 7, "bread"),
    "naan garlic":                  ("0114", 4.50, 2, "bread"),
    "naan butter garlic":           ("0118", 4.50, 0, "bread"),
    "naan butter":                  ("0117", 4.00, 0, "bread"),
    "naan mumtaj":                  ("0122", 8.00, 0, "bread"),
    "naan tajmahal":                ("0123", 9.00, 0, "bread"),
    "naan biasa":                   ("0111", 3.00, 11, "bread"),

    # === NASI / RICE ===
    "nasi ayam bawang sayur":       ("0156", 11.00, 16, "rice"),
    "nasi ayam bawang":             ("0154", 10.59, 23, "rice"),
    "nasi ayam sayur":              ("0157", 8.03, 30, "rice"),
    "nasi ayam rendang":            ("0158", 10.00, 0, "rice"),
    "nasi ayam":                    ("0151", 7.52, 48, "rice"),
    "nasi putih":                   ("0164", 2.33, 16, "rice"),
    "nasi daging":                  ("0168", 10.00, 0, "rice"),
    "nasi lemak bungkus":           ("0177", 2.60, 11, "rice"),
    "nasi bujang":                  ("", 5.00, 1, "rice"),
    "nasi goreng ayam":             ("0227", 10.50, 17, "rice"),
    "nasi goreng ayam mamak":       ("", 10.79, 7, "rice"),
    "nasi goreng ayam kunyit":      ("", 9.50, 1, "rice"),
    "nasi goreng kampung mamak":    ("", 6.50, 2, "rice"),
    "nasi putih ayam rempah sayur": ("", 11.00, 1, "rice"),
    "nasi putih ikan":              ("", 10.00, 2, "rice"),
    "nasi ikan sayur":              ("", 10.50, 1, "rice"),
    "nasi sayur":                   ("", 3.50, 1, "rice"),
    "nasi tambah":                  ("", 1.00, 1, "rice"),
    "kambing nasi putih":           ("", 14.50, 1, "rice"),
    "kambing nasi sayur":           ("", 15.00, 2, "rice"),

    # === BRIYANI ===
    "briyani ayam bawang set":      ("0178", 17.00, 1, "rice"),
    "briyani ayam bawang":          ("0182", 15.50, 1, "rice"),
    "briyani ayam goreng set":      ("0180", 14.00, 0, "rice"),
    "briyani ayam":                 ("0181", 10.00, 0, "rice"),
    "briyani kambing set":          ("0184", 20.00, 0, "rice"),
    "briyani kambing":              ("0185", 19.00, 1, "rice"),
    "briyani daging set":           ("0186", 18.00, 0, "rice"),
    "briyani lamb shank":           ("0200", 25.00, 0, "rice"),
    "briyani ayambawang telur":     ("", 16.00, 1, "rice"),
    "briyani kambing telur":        ("", 21.00, 1, "rice"),

    # === NASI GORENG ===
    "nasi goreng kampung":          ("0203", 6.56, 16, "rice"),
    "nasi goreng biasa":            ("0204", 6.10, 10, "rice"),
    "nasi goreng mamak":            ("0205", 6.00, 1, "rice"),
    "nasi goreng pattaya":          ("0206", 8.20, 5, "rice"),
    "nasi goreng seafood":          ("0215", 11.00, 0, "rice"),
    "nasi goreng cina":             ("", 6.50, 1, "rice"),
    "nasi goreng daging":           ("", 10.80, 4, "rice"),
    "nasi goreng ikan masin":       ("", 8.00, 1, "rice"),
    "nasi goreng paprik ayam":      ("", 9.50, 1, "rice"),
    "nasi goreng telur mata":       ("", 8.00, 2, "rice"),
    "nasi goreng tomyam":           ("", 9.50, 2, "rice"),

    # === MEE & MAGGI ===
    "maggi goreng telur mata":      ("", 7.50, 12, "noodle"),
    "maggi goreng kambing":         ("", 13.00, 0, "noodle"),
    "maggi goreng daging":          ("", 9.50, 0, "noodle"),
    "maggi goreng ayam":            ("", 9.50, 0, "noodle"),
    "maggi goreng ayam mamak":      ("", 10.50, 7, "noodle"),
    "maggi goreng ayam double":     ("", 13.00, 1, "noodle"),
    "maggi goreng mamak":           ("", 6.00, 0, "noodle"),
    "maggi goreng basa":            ("", 7.00, 0, "noodle"),
    "maggi goreng":                 ("", 6.00, 14, "noodle"),
    "maggi goreng double":          ("", 10.00, 1, "noodle"),
    "maggi goreng veg":             ("", 8.00, 1, "noodle"),
    "maggi tomyam":                 ("", 7.00, 0, "noodle"),
    "maggi sup":                    ("", 6.00, 7, "noodle"),
    "mee goreng telur mata":        ("", 7.50, 5, "noodle"),
    "mee goreng seafood":           ("", 9.50, 0, "noodle"),
    "mee goreng daging":            ("", 9.50, 0, "noodle"),
    "mee goreng mamak":             ("", 6.00, 17, "noodle"),
    "mee goreng ayam":              ("", 9.50, 0, "noodle"),
    "mee goreng ayam mamak":        ("", 10.50, 1, "noodle"),
    "mee goreng":                   ("", 6.00, 0, "noodle"),
    "mee goreng tampa":             ("", 8.00, 1, "noodle"),
    "mee campur bihun":             ("", 6.00, 0, "noodle"),
    "mee rebus":                    ("", 6.00, 0, "noodle"),
    "mee sup":                      ("", 6.00, 0, "noodle"),
    "mee open rm":                  ("", 3.50, 1, "noodle"),
    "rojak mee":                    ("", 7.00, 1, "noodle"),

    # === BIHUN & KUEY TEOW ===
    "bihun goreng telur mata":      ("", 7.50, 2, "noodle"),
    "bihun goreng mamak":           ("", 6.50, 3, "noodle"),
    "bihun goreng":                 ("", 6.00, 0, "noodle"),
    "bihun goreng ayam mamak":      ("", 10.50, 1, "noodle"),
    "bihun goreng basa":            ("", 7.00, 1, "noodle"),
    "bihun goreng singapore":       ("", 9.50, 1, "noodle"),
    "bihun goreng tomyam":          ("", 9.50, 1, "noodle"),
    "bihun sup":                    ("", 7.00, 2, "noodle"),
    "bihun tomyam":                 ("", 8.50, 3, "noodle"),
    "kuey teow goreng mamak":       ("", 6.00, 1, "noodle"),
    "kuey teow goreng basa":        ("", 8.00, 1, "noodle"),
    "kuey teow goreng telur mata":  ("", 7.50, 2, "noodle"),
    "kuey teow goreng":             ("", 6.00, 0, "noodle"),
    "kuey teow tomyam":             ("", 7.00, 0, "noodle"),
    "kuey teow kungfu":             ("", 9.50, 1, "noodle"),
    "kuey teow ladna":              ("", 8.00, 1, "noodle"),

    # === INDOMEE ===
    "indomee goreng":               ("", 5.50, 2, "noodle"),
    "indomee double":               ("", 8.50, 0, "noodle"),
    "indomee kosong":               ("", 4.50, 0, "noodle"),
    "indomee ayam dbl":             ("", 14.00, 1, "noodle"),

    # === LAUK / SIDE DISHES ===
    "kambing mysur":                ("0243", 15.00, 0, "lauk"),
    "ayam goreng":                  ("0247", 5.00, 25, "lauk"),
    "ayam goreng kunyit":           ("", 8.00, 1, "lauk"),
    "ayam bawang":                  ("0248", 8.50, 2, "lauk"),
    "ayam tandoori":                ("0249", 8.50, 12, "lauk"),
    "ayam rendang":                 ("0251", 8.00, 0, "lauk"),
    "ayam kari":                    ("0254", 7.00, 0, "lauk"),
    "daging rendang":               ("0258", 10.00, 0, "lauk"),
    "telur mata":                   ("", 1.50, 18, "lauk"),
    "telur 1/2 masak":              ("", 2.60, 8, "lauk"),
    "telur 3/4 masak":              ("", 2.60, 1, "lauk"),
    "telur dadar":                  ("", 2.00, 8, "lauk"),
    "telur goreng":                 ("", 1.50, 4, "lauk"),
    "telur masin":                  ("", 1.50, 11, "lauk"),
    "telur rebus":                  ("", 1.50, 9, "lauk"),
    "telur sambal":                 ("", 2.00, 2, "lauk"),
    "telur sotong besar":           ("", 10.00, 4, "lauk"),
    "telur sotong medium":          ("", 8.00, 1, "lauk"),
    "telur ikan besar":             ("", 10.00, 1, "lauk"),
    "telur ikan medium":            ("", 8.00, 1, "lauk"),
    "paprik ayam":                  ("", 8.00, 1, "lauk"),
    "sup kosong":                   ("", 1.00, 3, "lauk"),
    "sup sayur":                    ("", 7.00, 1, "lauk"),
    "tomyam ayam":                  ("", 7.00, 9, "lauk"),
    "tomyam campur":                ("", 9.00, 1, "lauk"),
    "tomyam seafood":               ("", 12.50, 1, "lauk"),
    "papadom":                      ("", 1.00, 9, "other"),
    "chicken chop":                 ("", 14.90, 2, "other"),
    "dry cilli chicken":            ("", 10.00, 1, "other"),
    "french fries":                 ("", 6.00, 7, "other"),
    "idly 1pc":                     ("", 1.30, 7, "other"),
    "rojak biasa":                  ("", 5.50, 1, "other"),

    # === MINUMAN (DRINKS) ===
    "milo":                         ("", 2.80, 8, "drink"),
    "milo ais":                     ("", 3.30, 34, "drink"),
    "milo ais jumbo":               ("", 8.00, 1, "drink"),
    "milo panas":                   ("", 2.80, 0, "drink"),
    "teh":                          ("", 1.70, 60, "drink"),
    "teh ais":                      ("", 2.60, 37, "drink"),
    "teh ais jumbo":                ("", 5.90, 1, "drink"),
    "teh c":                        ("", 1.70, 2, "drink"),
    "teh halia":                    ("", 2.00, 6, "drink"),
    "teh khulafa big":              ("", 2.50, 2, "drink"),
    "teh masala":                   ("", 4.07, 7, "drink"),
    "teh o":                        ("", 1.50, 18, "drink"),
    "teh o ais":                    ("", 2.10, 99, "drink"),
    "teh o ais jumbo":              ("", 5.00, 3, "drink"),
    "teh o ais limau jumbo":        ("", 5.50, 1, "drink"),
    "teh o lemon ais":              ("", 4.00, 2, "drink"),
    "teh o lemon panas":            ("", 3.50, 1, "drink"),
    "teh o limau":                  ("", 1.70, 1, "drink"),
    "teh o limau ais":              ("", 2.50, 17, "drink"),
    "teh o lychee jumbo":           ("", 9.00, 1, "drink"),
    "teh tarik":                    ("", 2.00, 0, "drink"),
    "kopi":                         ("", 1.70, 1, "drink"),
    "kopi ais":                     ("", 2.60, 4, "drink"),
    "kopi o":                       ("", 1.50, 5, "drink"),
    "kopi o ais":                   ("", 2.10, 4, "drink"),
    "kopi panas":                   ("", 1.70, 0, "drink"),
    "jumbo kopi o ais":             ("", 5.00, 1, "drink"),
    "nescafe":                      ("", 2.80, 5, "drink"),
    "nescafe ais":                  ("", 3.70, 10, "drink"),
    "nescafe c":                    ("", 2.80, 1, "drink"),
    "nescafe o":                    ("", 2.50, 3, "drink"),
    "nescafe o ais":                ("", 3.00, 3, "drink"),
    "neslo ais":                    ("", 4.00, 2, "drink"),
    "horlicks":                     ("", 3.00, 1, "drink"),
    "horlicks ais":                 ("", 4.50, 2, "drink"),
    "bandung":                      ("", 2.50, 0, "drink"),
    "bandung ais":                  ("", 3.00, 0, "drink"),
    "bandung panas":                ("", 2.50, 0, "drink"),
    "sirap ais":                    ("", 2.00, 5, "drink"),
    "sirap bandung ais":            ("", 3.00, 2, "drink"),
    "sirap limau ais":              ("", 2.70, 2, "drink"),
    "sirap lychee ais":             ("", 4.60, 1, "drink"),
    "sirap panas":                  ("", 1.80, 0, "drink"),
    "barli ais":                    ("", 2.50, 4, "drink"),
    "barli panas":                  ("", 2.00, 3, "drink"),
    "barli limau panas":            ("", 2.30, 1, "drink"),
    "lemon ais":                    ("", 3.77, 7, "drink"),
    "lemon panas":                  ("", 3.20, 1, "drink"),
    "limau ais":                    ("", 2.57, 14, "drink"),
    "limau ais jumbo":              ("", 5.00, 1, "drink"),
    "limau panas":                  ("", 1.80, 2, "drink"),
    "lychee ais":                   ("", 4.75, 2, "drink"),
    "air kosong":                   ("", 0.30, 0, "drink"),
    "air panas":                    ("", 0.30, 8, "drink"),
    "air suam":                     ("", 0.30, 32, "drink"),
    "air mineral":                  ("", 1.50, 0, "drink"),
    "ais kosong":                   ("", 0.30, 133, "drink"),
    "ais batu":                     ("", 1.00, 4, "drink"),
    "air tin":                      ("", 2.60, 3, "drink"),
    "air tin open":                 ("", 0.50, 1, "drink"),
    "tube ais":                     ("", 1.80, 9, "drink"),
    "100 plus":                     ("", 2.60, 1, "drink"),
    "coke tin":                     ("", 2.60, 1, "drink"),
    "apple juice":                  ("", 6.00, 1, "drink"),
    "orange juice":                 ("", 6.00, 1, "drink"),
    "watermelon juice":             ("", 6.00, 2, "drink"),
    "kelapa muda":                  ("", 5.50, 5, "drink"),
    "honey lemon":                  ("", 3.80, 1, "drink"),
    "extra joss angur":             ("", 4.00, 14, "drink"),
    "extra joss mangga":            ("", 4.00, 6, "drink"),
    "extra joss ori":               ("", 4.00, 4, "drink"),
    "jumbo extra jus":              ("", 6.50, 1, "drink"),
    "tea masala":                    ("", 3.70, 1, "drink"),
    "bru coffee":                   ("", 3.00, 1, "drink"),
    "carrot susu":                  ("", 6.50, 1, "drink"),
    "cincau":                       ("", 3.00, 0, "drink"),
    "longan":                       ("", 3.50, 0, "drink"),
    "mineral water big":            ("", 2.50, 7, "drink"),
    "mineral water small":          ("", 1.50, 6, "drink"),

    # === OTHER ===
    "jumbo glass":                  ("", 1.50, 3, "other"),
    "kacang 2.00":                  ("", 2.00, 3, "other"),
    "kacang rm":                    ("", 1.00, 1, "other"),
}

# Convert tuple format to dict format for consistent access
MENU = {k: {"audio_id": v[0], "price": v[1], "popularity": v[2], "category": v[3]} for k, v in MENU.items()}


# ================================================================
# ICONIC_DRINKS_FLOOR — workaround for missing POS SKUs
# ================================================================
# The 06-Apr-2026 POS export (source for the popularity field above)
# is missing entire SKUs for several universally-ordered drinks:
# teh tarik, milo panas, kopi panas, bandung, air kosong, cincau, longan.
# These items land with popularity=0 even though they are daily-ordered
# at any Malaysian mamak. That zero silently demotes them in:
#   - fuzzy-match tie-break (menu_validator.py)
#   - top-30 best-sellers injected into the DeepSeek prompt (main.py)
# Root cause: Yassir's POS aggregates default preparations under a single
# base SKU (e.g. "Teh" = teh tarik by default), so the variant never
# appears as its own row.
#
# The floor below is a CONSERVATIVE INDUSTRY ESTIMATE, not real sales
# data. It exists only to keep these items non-zero so downstream
# consumers don't erase them. REMOVE this block (or set every value to 0)
# once a fresh POS export that itemizes hot-vs-iced and tarik-vs-plain
# variants as separate SKUs is merged in. See docs/POS_DATA_TODO.md.
#
# Tuning rule: only raise values, never lower. Real POS data always wins.
ICONIC_DRINKS_FLOOR = {
    "teh tarik":     50,   # THE signature mamak drink, often default "teh"
    "kopi panas":    15,   # Breakfast staple
    "kopi o panas":  10,
    "milo panas":    12,   # Breakfast staple
    "sirap panas":    5,
    "bandung":       15,
    "bandung ais":   10,
    "bandung panas":  3,
    "air kosong":    20,   # Free refill requests
    "cincau":         8,
    "longan":         8,
}


def apply_popularity_floor(menu_dict: dict) -> dict:
    """Apply popularity floor for iconic items missing from POS export.

    Only raises values, never lowers — safe idempotent op.
    """
    for item, floor in ICONIC_DRINKS_FLOOR.items():
        if item in menu_dict:
            current = menu_dict[item].get("popularity", 0)
            if current < floor:
                menu_dict[item]["popularity"] = floor
                print(f"[PopFloor] '{item}' {current} -> {floor}")
    return menu_dict


apply_popularity_floor(MENU)

# Common audio responses used across the app
AUDIO_RESPONSES = {
    "ada_lagi": "0043",
    "terima_kasih": "0021",
    "boleh_ulang": "0045",
    "greeting_pagi": "0005",
    "greeting_tengahari": "0006",
    "greeting_petang": "0007",
    "greeting_malam": "0008",
}

# Pre-sorted menu keys by length descending (greedy matching)
_SORTED_KEYS = sorted(MENU.keys(), key=len, reverse=True)


class OrderEngine:
    """Rule-based order processing engine."""

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def process(self, speech_text: str, current_order: list) -> dict:
        """
        Process customer speech and return structured result.

        Parameters
        ----------
        speech_text : str
            Raw transcription from speech recognition.
        current_order : list
            Current order items [{name, qty, price}, ...].

        Returns
        -------
        dict with keys: text, audio_ids, new_items, action, order, total
        """
        text = speech_text.strip().lower()

        if not text:
            return self._response(
                text="Maaf, boleh ulang?",
                audio_ids=["0045"],
                action="unknown",
                order=current_order,
            )

        # 1. Check for end / confirm phrases
        if self._matches_phrase(text, END_PHRASES):
            return self._build_confirm(current_order)

        # 2. Extract menu items from speech
        found_items = self._extract_items(text)

        if not found_items:
            return self._response(
                text="Maaf, boleh ulang?",
                audio_ids=["0045"],
                action="unknown",
                order=current_order,
            )

        # 3. Check for ambiguous matches (partial speech → multiple possible items)
        ambiguous = self._find_ambiguous(found_items)
        if ambiguous:
            ambiguous_names = {a["matched"] for a in ambiguous}
            clear_items = [
                (n, q, a, p) for n, q, a, p in found_items
                if n not in ambiguous_names
            ]
            return self._build_disambiguate(ambiguous, clear_items, current_order)

        # 4. Build response — item audio + "Ada lagi?" only, nothing else
        return self._build_add_items(found_items, current_order)

    def get_greeting(self) -> dict:
        """Return time-appropriate greeting with audio IDs."""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return {
                "text": "Selamat pagi! Saya Aisha, boleh saya ambil pesanan anda?",
                "audio_ids": ["0005"],
            }
        elif 12 <= hour < 15:
            return {
                "text": "Selamat tengah hari! Saya Aisha, nak pesan apa hari ini?",
                "audio_ids": ["0006"],
            }
        elif 15 <= hour < 19:
            return {
                "text": "Selamat petang! Saya Aisha, boleh saya ambil pesanan anda?",
                "audio_ids": ["0007"],
            }
        else:
            return {
                "text": "Selamat malam! Saya Aisha, selamat datang ke Khulafa Bistro.",
                "audio_ids": ["0008"],
            }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _matches_phrase(text: str, phrases: list) -> bool:
        """Check if the text contains any of the given phrases."""
        for phrase in phrases:
            if phrase in text:
                return True
        return False

    @staticmethod
    def _extract_items(text: str) -> list:
        """
        Extract menu items with quantities using greedy longest-match.
        Returns list of (name, qty, audio_id, price).

        Uses a character-level 'used' mask so every occurrence of
        every menu item is found, longest-first, without overlap.
        """
        text = re.sub(r'\s+', ' ', text.strip())
        length = len(text)
        used = [False] * length
        results = []

        for key in _SORTED_KEYS:
            klen = len(key)
            start = 0
            while start <= length - klen:
                idx = text.find(key, start)
                if idx == -1:
                    break

                # Skip if any character in this span is already used
                if any(used[idx:idx + klen]):
                    start = idx + 1
                    continue

                # Mark characters as used
                for i in range(idx, idx + klen):
                    used[i] = True

                # --- Detect quantity ---
                qty = 1
                found_qty_before = False
                before = text[:idx].rstrip()

                # Digit right before: "2 roti canai"
                digit_match = re.search(r'(\d+)\s*$', before)
                if digit_match:
                    qty = int(digit_match.group(1))
                    found_qty_before = True
                else:
                    # Malay number word: "dua roti canai"
                    for word, num in MALAY_NUMBERS.items():
                        if before.endswith(word):
                            qty = num
                            found_qty_before = True
                            break

                # Only check after if no quantity found before
                if not found_qty_before:
                    after = text[idx + klen:].lstrip()
                    after_first = after.split()[0] if after.split() else ""
                    digit_after = re.match(r'^(\d+)$', after_first)
                    if digit_after:
                        qty = int(digit_after.group(1))
                    elif after_first in MALAY_NUMBERS:
                        qty = MALAY_NUMBERS[after_first]

                audio_id = MENU[key]["audio_id"]
                price = MENU[key]["price"]
                results.append((key, qty, audio_id, price))

                start = idx + klen

        # Debug: show what items were matched from the speech text
        if results:
            matched_names = [f"{name} (qty={qty}, audio={aid})" for name, qty, aid, _ in results]
            print(f"[OrderEngine] Speech: '{text}' → Matched: {matched_names}")
        else:
            print(f"[OrderEngine] Speech: '{text}' → No items matched")

        return results

    def _find_ambiguous(self, found_items: list) -> list:
        """
        Check if any matched items have longer alternatives from
        a different category (different first word).

        E.g. "ayam bawang" is ambiguous because "nasi ayam bawang"
        and "briyani ayam bawang set" also exist.
        But "roti canai" is NOT ambiguous vs "roti canai susu" (same category).
        """
        ambiguous = []
        for name, qty, audio_id, price in found_items:
            first_word = name.split()[0]
            alternatives = []
            for menu_key in _SORTED_KEYS:
                if menu_key == name:
                    continue
                if name not in menu_key:
                    continue
                # Only flag as ambiguous if the longer item starts
                # with a different word (different category)
                other_first = menu_key.split()[0]
                if other_first != first_word:
                    alt_price = MENU[menu_key]["price"]
                    alternatives.append({
                        "name": menu_key.title(),
                        "price": alt_price,
                    })
            if alternatives:
                # Include the exact match itself as an option
                alternatives.append({
                    "name": name.title(),
                    "price": price,
                })
                # Sort by price descending
                alternatives.sort(key=lambda x: -x["price"])
                ambiguous.append({
                    "matched": name,
                    "qty": qty,
                    "options": alternatives,
                })
        return ambiguous

    def _build_disambiguate(self, ambiguous: list, clear_items: list,
                            current_order: list) -> dict:
        """Build disambiguation response when speech is ambiguous."""
        # Add any clear (non-ambiguous) items to the order first
        updated_order = list(current_order)
        clear_new = []
        clear_audio = []
        clear_names = []

        for name, qty, audio_id, price in clear_items:
            item = {"name": name.title(), "qty": qty, "price": price}
            clear_new.append(item)
            if audio_id:
                clear_audio.append(audio_id)
            display = name.title()
            if qty > 1:
                display = f"{qty} {display}"
            clear_names.append(display)

            merged = False
            for existing in updated_order:
                if existing.get("name", "").lower() == item["name"].lower():
                    existing["qty"] = existing.get("qty", 1) + item["qty"]
                    merged = True
                    break
            if not merged:
                updated_order.append(dict(item))

        total = sum(i.get("price", 0) * i.get("qty", 1) for i in updated_order)

        # Build text message
        matched_names = [a["matched"].title() for a in ambiguous]
        text_parts = []
        if clear_names:
            text_parts.append(", ".join(clear_names))
        text_parts.append(f"{', '.join(matched_names)} — yang mana satu?")
        text = ". ".join(text_parts)

        return self._response(
            text=text,
            audio_ids=clear_audio,  # only play audio for clear items, not ambiguous
            action="disambiguate",
            new_items=clear_new,
            order=updated_order,
            total=total,
            disambiguate=ambiguous,
        )

    def _build_add_items(self, found_items: list, current_order: list) -> dict:
        """Build response for adding items to order."""
        new_items = []
        audio_ids = []
        names = []

        for name, qty, audio_id, price in found_items:
            new_items.append({
                "name": name.title(),
                "qty": qty,
                "price": price,
            })
            if audio_id:
                audio_ids.append(audio_id)
            display = name.title()
            if qty > 1:
                display = f"{qty} {display}"
            names.append(display)

        # Append "Ada lagi?" prompt
        audio_ids.append("0043")

        # Merge new items into current order
        updated_order = list(current_order)
        for item in new_items:
            merged = False
            for existing in updated_order:
                if existing.get("name", "").lower() == item["name"].lower():
                    existing["qty"] = existing.get("qty", 1) + item["qty"]
                    merged = True
                    break
            if not merged:
                updated_order.append(dict(item))

        total = sum(i.get("price", 0) * i.get("qty", 1) for i in updated_order)

        # Build natural text
        if len(names) == 1:
            items_text = names[0]
        else:
            items_text = ", ".join(names[:-1]) + " dan " + names[-1]

        # --- Upsell: check for profit-driven suggestions ---
        upsell = self._get_upsell_for_items(found_items)

        if upsell:
            # Append upsell text naturally after item confirmation
            text = f"{items_text}. {upsell['suggestion_text']}"
        else:
            text = f"{items_text}. Ada apa-apa lagi?"

        result = self._response(
            text=text,
            audio_ids=audio_ids,
            action="add_items",
            new_items=new_items,
            order=updated_order,
            total=total,
        )
        if upsell:
            result["upsell"] = upsell
        return result

    def _get_upsell_for_items(self, found_items: list) -> dict | None:
        """Check found items for upsell opportunities (first match wins)."""
        try:
            from upsell_engine import get_upsell_engine
            upsell_eng = get_upsell_engine()
            for name, qty, audio_id, price in found_items:
                suggestion = upsell_eng.get_upsell(name)
                if suggestion:
                    return suggestion
        except Exception as e:
            print(f"[OrderEngine] Upsell check failed: {e}")
        return None

    def _build_confirm(self, current_order: list) -> dict:
        """Build confirmation response."""
        if not current_order:
            return self._response(
                text="Anda belum order apa-apa lagi. Nak order apa?",
                audio_ids=["0043"],
                action="no_items",
                order=[],
            )

        total = sum(i.get("price", 0) * i.get("qty", 1) for i in current_order)
        items_text = ", ".join(
            f"{i.get('qty', 1)} {i['name']}" for i in current_order
        )

        return self._response(
            text="Terima kasih! Order dihantar.",
            audio_ids=["0021"],
            action="confirm_order",
            order=current_order,
            total=total,
        )

    @staticmethod
    def _response(text, audio_ids, action, order=None, new_items=None, total=0,
                  disambiguate=None):
        result = {
            "text": text,
            "audio_ids": audio_ids,
            "action": action,
            "new_items": new_items or [],
            "order": order or [],
            "total": total,
        }
        if disambiguate:
            result["disambiguate"] = disambiguate
        return result


# ------------------------------------------------------------------ #
#  Singleton accessor                                                  #
# ------------------------------------------------------------------ #

_engine_instance = None


def get_engine() -> OrderEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = OrderEngine()
    return _engine_instance
