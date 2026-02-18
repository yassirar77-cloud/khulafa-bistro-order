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

# Recommendation phrases
RECOMMEND_PHRASES = [
    "apa sedap", "apa yang sedap", "apa best",
    "recommend", "rekomen", "cadang", "cadangkan",
    "apa popular", "apa laris", "bestseller", "best seller",
    "suggest", "apa bagus", "menu popular",
    "nak tahu apa sedap", "apa favourite",
]

# Full menu: name → (audio_id, price)
MENU = {
    # === ROTI ===
    "roti canai susu":          ("0081", 3.00),
    "roti canai":               ("0051", 2.00),
    "roti telur bawang":        ("0057", 3.50),
    "roti telur cheese":        ("0059", 4.50),
    "roti telur":               ("0054", 3.00),
    "roti sardin":              ("0060", 4.00),
    "roti khawin":              ("0062", 2.50),
    "roti boom kaya":           ("0064", 3.50),
    "roti boom":                ("0063", 3.00),
    "roti tissue":              ("0065", 3.00),
    "roti pisang cheese":       ("0067", 4.50),
    "roti pisang":              ("0066", 3.50),
    "roti planta":              ("0069", 3.00),
    "roti cheese":              ("0072", 3.50),
    "roti bawang":              ("0073", 2.50),
    "roti jantan":              ("0075", 4.00),
    "roti special double":      ("0080", 7.00),
    "roti special":             ("0079", 5.00),
    "roti milo":                ("0082", 3.50),
    "roti kaya":                ("0083", 2.50),
    "roti bakar kaya":          ("0087", 3.50),
    "roti bakar cheese":        ("0089", 4.00),
    "roti bakar":               ("0086", 3.00),
    "murtabak ayam":            ("0092", 9.00),
    "murtabak daging":          ("0093", 10.00),
    "murtabak kambing":         ("0094", 12.00),

    # === NAAN ===
    "naan mozzerella cheese":   ("0112", 6.00),
    "naan cheese garlic":       ("0115", 5.50),
    "naan cheese double":       ("0120", 7.00),
    "naan cheese":              ("0113", 5.00),
    "naan garlic":              ("0114", 4.00),
    "naan butter garlic":       ("0118", 4.50),
    "naan butter":              ("0117", 4.00),
    "naan mumtaj":              ("0122", 8.00),
    "naan tajmahal":            ("0123", 9.00),
    "naan biasa":               ("0111", 3.00),

    # === NASI ===
    "nasi ayam bawang sayur":   ("0156", 10.00),
    "nasi ayam bawang":         ("0154", 9.00),
    "nasi ayam sayur":          ("0157", 9.00),
    "nasi ayam rendang":        ("0158", 10.00),
    "nasi ayam":                ("0151", 8.00),
    "nasi putih":               ("0164", 2.00),
    "nasi daging":              ("0168", 10.00),
    "nasi lemak bungkus":       ("0177", 3.00),

    # === BRIYANI ===
    "briyani ayam bawang set":  ("0178", 15.00),
    "briyani ayam goreng set":  ("0180", 14.00),
    "briyani ayam":             ("0181", 10.00),
    "briyani kambing set":      ("0184", 20.00),
    "briyani kambing":          ("0185", 15.00),
    "briyani daging set":       ("0186", 18.00),
    "briyani lamb shank":       ("0200", 25.00),

    # === NASI GORENG ===
    "nasi goreng kampung":      ("0203", 8.00),
    "nasi goreng biasa":        ("0204", 7.00),
    "nasi goreng mamak":        ("0205", 8.00),
    "nasi goreng pattaya":      ("0206", 9.00),
    "nasi goreng seafood":      ("0215", 11.00),
    "nasi goreng ayam":         ("0227", 9.00),

    # === LAUK ===
    "kambing mysur":            ("0243", 15.00),
    "ayam goreng":              ("0247", 6.00),
    "ayam bawang":              ("0248", 7.00),
    "ayam tandoori":            ("0249", 8.00),
    "ayam rendang":             ("0251", 8.00),
    "ayam kari":                ("0254", 7.00),
    "daging rendang":           ("0258", 10.00),
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
                text="Maaf, saya tak dengar. Boleh ulang?",
                audio_ids=["0043"],
                action="no_input",
                order=current_order,
            )

        # 1. Check for end / confirm phrases
        if self._matches_phrase(text, END_PHRASES):
            return self._build_confirm(current_order)

        # 2. Check for recommendation request
        if self._matches_phrase(text, RECOMMEND_PHRASES):
            return self._response(
                text="Bestseller kami nasi ayam bawang, roti canai, dan maggi goreng.",
                audio_ids=["0038", "0043"],
                action="recommend",
                order=current_order,
            )

        # 3. Extract menu items from speech
        found_items = self._extract_items(text)

        if not found_items:
            return self._response(
                text="Maaf, saya tak pasti apa yang anda nak. Boleh ulang?",
                audio_ids=["0043"],
                action="not_found",
                order=current_order,
            )

        # 4. Build response
        return self._build_add_items(found_items, current_order)

    def get_greeting(self) -> dict:
        """Return time-appropriate greeting with audio IDs."""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return {
                "text": "Selamat pagi! Saya Aisha. Nak order apa hari ini?",
                "audio_ids": ["0005"],
            }
        elif 12 <= hour < 15:
            return {
                "text": "Selamat tengahari! Saya Aisha. Nak makan apa?",
                "audio_ids": ["0006"],
            }
        elif 15 <= hour < 19:
            return {
                "text": "Selamat petang! Saya Aisha. Jemput order.",
                "audio_ids": ["0007"],
            }
        else:
            return {
                "text": "Selamat malam! Saya Aisha. Selamat datang.",
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

                audio_id, price = MENU[key]
                results.append((key, qty, audio_id, price))

                start = idx + klen

        return results

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

        return self._response(
            text=f"{items_text}. Ada apa-apa lagi?",
            audio_ids=audio_ids,
            action="add_items",
            new_items=new_items,
            order=updated_order,
            total=total,
        )

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
            text=f"Okay, pesanan anda: {items_text}. Jumlah RM{total:.2f}. Terima kasih!",
            audio_ids=["0021"],
            action="confirm_order",
            order=current_order,
            total=total,
        )

    @staticmethod
    def _response(text, audio_ids, action, order=None, new_items=None, total=0):
        return {
            "text": text,
            "audio_ids": audio_ids,
            "action": action,
            "new_items": new_items or [],
            "order": order or [],
            "total": total,
        }


# ------------------------------------------------------------------ #
#  Singleton accessor                                                  #
# ------------------------------------------------------------------ #

_engine_instance = None


def get_engine() -> OrderEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = OrderEngine()
    return _engine_instance
