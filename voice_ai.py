import os
import json
from anthropic import Anthropic

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

SYSTEM_PROMPT = """Kamu adalah Aisha, friendly waitress di Khulafa Bistro. Kamu ambil order customer melalui voice.

RULES:
- Jawab PENDEK je, max 2-3 ayat
- Campur Malay & English naturally
- Focus on ORDER sahaja, jangan chit-chat
- Bila customer sebut item, confirm terus dengan harga
- Tunjuk running total
- Bila customer kata "dah cukup" / "confirm" / "that's all" / "sudah", confirm order dan set order_confirmed = true
- Kalau item tak ada dalam menu, cakap "Sorry, item tu takde. Nak try yang lain?"
- Guna RM for prices

MENU ITEMS AVAILABLE:
{menu_items}

RESPONSE FORMAT:
Always respond with valid JSON only, no other text:
{{
  "response": "your response text here",
  "order_confirmed": false,
  "extracted_items": []
}}

When items are being ordered, include them in extracted_items:
{{
  "response": "Roti canai satu, RM1.50. Nak tambah lagi?",
  "order_confirmed": false,
  "extracted_items": [{{"name": "Roti Canai", "quantity": 1, "price": 1.50}}]
}}

When customer confirms (says "confirm", "dah cukup", "okay", "yes", "sudah", "that's all"):
{{
  "response": "Terima kasih! Order dah hantar ke cashier.",
  "order_confirmed": true,
  "extracted_items": [{{"name": "Roti Canai", "quantity": 1, "price": 1.50}}]
}}

IMPORTANT: Always keep track of ALL items ordered throughout the conversation in extracted_items. Match item names to the closest menu item available. If quantity not specified, assume 1."""


class VoiceAI:
    def __init__(self):
        self.client = Anthropic(api_key=CLAUDE_API_KEY)

    def chat(self, user_message: str, history: list, table_number: str, menu_items: list) -> dict:
        """Process a voice message and return AI response with order extraction."""
        menu_text = "\n".join(
            f"- {item['name']} ({item['category']}) - RM{item['price']:.2f}"
            for item in menu_items
        )

        system = SYSTEM_PROMPT.format(menu_items=menu_text)

        # Build messages from history
        messages = []
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        messages.append({"role": "user", "content": user_message})

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=system,
                messages=messages,
            )

            response_text = response.content[0].text.strip()

            # Parse JSON response
            try:
                parsed = json.loads(response_text)
                return {
                    "response": parsed.get("response", response_text),
                    "order_confirmed": parsed.get("order_confirmed", False),
                    "extracted_items": parsed.get("extracted_items", []),
                }
            except json.JSONDecodeError:
                # If Claude didn't return JSON, wrap it
                return {
                    "response": response_text,
                    "order_confirmed": False,
                    "extracted_items": [],
                }

        except Exception as e:
            print(f"Voice AI error: {e}")
            return {
                "response": "Sorry, ada masalah teknikal. Cuba lagi ya.",
                "order_confirmed": False,
                "extracted_items": [],
            }

    def extract_order_items(self, conversation: list, menu_items: list) -> list:
        """Parse conversation to extract ordered items."""
        menu_text = "\n".join(
            f"- {item['name']} ({item['category']}) - RM{item['price']:.2f}"
            for item in menu_items
        )

        messages = [
            {
                "role": "user",
                "content": f"""Extract all ordered items from this conversation. Match to the menu below.

MENU:
{menu_text}

CONVERSATION:
{json.dumps(conversation)}

Return ONLY valid JSON array: [{{"name": "exact menu name", "quantity": 1, "price": 1.50}}]"""
            }
        ]

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=messages,
            )
            return json.loads(response.content[0].text.strip())
        except Exception:
            return []
