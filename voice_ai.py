"""
Voice AI Module - Qwen3 API + Pre-recorded Audio
===================================================
1. Customer speaks → text via Web Speech API
2. Text sent to Qwen3 API for conversational response
3. Qwen3's response matched to pre-recorded audio
4. Audio played back to customer (natural Malay voice)
5. Falls back to browser TTS if no audio match
"""

import os
from openai import OpenAI
from datetime import datetime
from aisha_voice import get_aisha


# Initialize Qwen3 client (OpenAI-compatible)
client = None

def get_client():
    global client
    if client is None:
        api_key = os.getenv("DASHSCOPE_API_KEY")
        base_url = os.getenv("QWEN_API_URL")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY not set")
        if not base_url:
            raise ValueError("QWEN_API_URL not set")
        client = OpenAI(api_key=api_key, base_url=base_url)
    return client


def get_time_of_day() -> str:
    """Get current time period for greeting selection."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 15:
        return "afternoon"
    elif 15 <= hour < 19:
        return "evening"
    else:
        return "night"


def build_system_prompt(table_number: str, menu_context: str) -> str:
    """Build the system prompt for Qwen3 with audio-matching instructions."""
    
    return f"""Kau adalah Aisha, pelayan virtual di restoran ini, Table {table_number}.

PERATURAN PENTING - IKUT BETUL-BETUL:

1. BAHASA: Bercakap dalam Bahasa Melayu campur. Boleh mix English sikit.

2. SANGAT RINGKAS: Maksimum 1-2 ayat sahaja setiap response.
   - JANGAN panjang lebar
   - Terus ke point

3. PERATURAN UTAMA - JANGAN SUGGEST MENU ITEMS:
   - Bila customer order, HANYA ulang balik apa yang dia order + tanya "Ada lagi?"
   - JANGAN sesekali list menu items atau suggest makanan specific
   - JANGAN sebut nama makanan yang customer TIDAK order
   - HANYA boleh suggest kalau customer SENDIRI tanya "apa yang sedap?" atau "recommend apa?"

4. FLOW ORDERING (IKUT BETUL-BETUL):
   Step 1 - Customer order makanan:
     Aisha: "[Sebut balik exact item yang customer order]. Ada lagi?"
     Contoh: Customer kata "roti canai dengan roti boom"
             Aisha: "Roti canai dan Roti Boom. Ada lagi?"

   Step 2 - Customer kata dah cukup ("tu je" / "dah" / "cukup"):
     Aisha: "Okay! Nak minum apa atau confirm order?"
     (Tanya pasal drinks SEKALI SAHAJA di sini - jangan ulang)

   Step 3 - Customer tambah drinks ATAU kata confirm:
     Kalau tambah drinks: "[Nama drinks]. Total RM[harga]. Confirm?"
     Kalau terus confirm: "Total RM[harga]. Confirm?"

   Step 4 - Customer confirm:
     Aisha: "Terima kasih! Order dah dihantar."

5. GUNA AYAT STANDARD INI bila boleh (sebab kita ada audio recording):
   GREETINGS:
   - "Selamat datang!" / "Welcome! Nak order apa?"
   - "Hai, saya Aisha. Boleh saya ambil pesanan anda?"

   CONFIRM ORDER:
   - Sebut nama item tepat macam menu: "Roti canai.", "Nasi ayam bawang.", "Teh O ais."

   TANYA LAGI:
   - "Ada lagi?"

   CLOSING:
   - "Terima kasih! Order dah dihantar."
   - "Terima kasih sebab datang ke restoran kami."

6. MENU ITEMS - Sebut TEPAT macam ni (jangan ubah nama):
{menu_context}

7. HARGA: Kalau customer tanya harga, bagitahu. Format: "RM X.XX"

8. JANGAN (PALING PENTING):
   - JANGAN list menu items atau categories
   - JANGAN suggest specific makanan unless customer minta recommendation
   - JANGAN sebut makanan yang customer tak order
   - JANGAN buat ayat panjang
   - JANGAN tanya soalan yang tak perlu
   - JANGAN tanya pasal drinks lebih dari sekali
"""


async def chat_with_voice(
    message: str,
    history: list,
    table_number: str,
    menu_context: str
) -> dict:
    """
    Process voice chat message and return response with matching audio.
    
    Returns:
        {
            "text": "Roti canai satu. Ada lagi?",
            "audio_matches": [
                {"id": "0052", "text": "Roti canai satu.", "audio_path": "/audio/wavs/0052.wav", "score": 0.95}
            ],
            "has_audio": true
        }
    """
    aisha = get_aisha()
    
    # Build conversation messages
    messages = []
    for h in history[-10:]:  # Keep last 10 messages for context
        messages.append({
            "role": h.get("role", "user"),
            "content": h.get("content", "")
        })
    messages.append({"role": "user", "content": message})
    
    # Call Qwen3 API
    try:
        model = os.getenv("QWEN_MODEL", "qwen3-plus")
        api_messages = [{"role": "system", "content": build_system_prompt(table_number, menu_context)}]
        api_messages.extend(messages)

        response = get_client().chat.completions.create(
            model=model,
            max_tokens=150,  # Keep responses short
            messages=api_messages,
            extra_body={"enable_thinking": False}
        )

        response_text = response.choices[0].message.content.strip()

    except Exception as e:
        print(f"[VoiceAI] Qwen3 API error: {e}")
        response_text = "Maaf, saya tak dapat dengar. Boleh ulang?"
    
    # Find matching audio for the response
    audio_matches = aisha.find_matches_in_response(response_text)
    
    # If no sentence-level matches, try the whole response
    if not audio_matches:
        whole_match = aisha.find_best_match(response_text, threshold=0.5)
        if whole_match:
            audio_matches = [whole_match]
    
    return {
        "text": response_text,
        "audio_matches": audio_matches,
        "has_audio": len(audio_matches) > 0
    }


def get_greeting_with_audio() -> dict:
    """Get a time-appropriate greeting with matching audio."""
    aisha = get_aisha()
    time_of_day = get_time_of_day()
    
    match = aisha.get_greeting(time_of_day)
    if match:
        return {
            "text": match["text"],
            "audio_matches": [match],
            "has_audio": True,
            "time_of_day": time_of_day
        }
    
    # Fallback
    return {
        "text": "Hai, saya Aisha. Boleh saya ambil pesanan anda?",
        "audio_matches": [],
        "has_audio": False,
        "time_of_day": time_of_day
    }
