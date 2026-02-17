"""
Voice AI Module - Claude API + Pre-recorded Audio
===================================================
1. Customer speaks → text via Web Speech API
2. Text sent to Claude API for conversational response
3. Claude's response matched to pre-recorded audio
4. Audio played back to customer (natural Malay voice)
5. Falls back to browser TTS if no audio match
"""

import os
import anthropic
from datetime import datetime
from aisha_voice import get_aisha


# Initialize Claude client
client = None

def get_client():
    global client
    if client is None:
        api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("CLAUDE_API_KEY or ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=api_key)
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
    """Build the system prompt for Claude with audio-matching instructions."""
    
    return f"""Kau adalah Aisha, pelayan virtual di restoran ini, Table {table_number}.

PERATURAN PENTING - IKUT BETUL-BETUL:

1. BAHASA: Bercakap dalam Bahasa Melayu campur. Boleh mix English sikit.

2. SANGAT RINGKAS: Maksimum 1-2 ayat sahaja setiap response. 
   - JANGAN panjang lebar
   - JANGAN ulang menu
   - Terus ke point

3. GUNA AYAT STANDARD INI bila boleh (sebab kita ada audio recording):
   GREETINGS:
   - "Selamat datang!" / "Welcome! Nak order apa?"
   - "Hai, saya Aisha. Boleh saya ambil pesanan anda?"
   
   CONFIRM ORDER:
   - Sebut nama item tepat macam menu: "Roti canai.", "Nasi ayam bawang.", "Teh O ais."
   - Guna format: "[Nama item]." (satu ayat, ada period)
   
   TANYA LAGI:
   - "Ada apa-apa lagi saya boleh bantu?"
   - "Nak tambah roti?" / "Nak tambah naan?"
   
   CLOSING:
   - "Terima kasih sebab datang ke restoran kami."

4. MENU ITEMS - Sebut TEPAT macam ni (jangan ubah nama):
{menu_context}

5. FLOW ORDERING:
   - Customer sebut makanan → Confirm nama item + tanya "Ada lagi?"
   - Customer kata "dah" / "cukup" / "tu je" → Baca order list + total + "Confirm?"
   - Customer confirm → "Terima kasih! Order dah dihantar."

6. HARGA: Kalau customer tanya harga, bagitahu. Format: "RM X.XX"

7. JANGAN:
   - Jangan buat cerita panjang
   - Jangan tanya soalan yang tak perlu
   - Jangan suggest banyak-banyak item sekaligus
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
    
    # Call Claude API
    try:
        response = get_client().messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,  # Keep responses short
            system=build_system_prompt(table_number, menu_context),
            messages=messages
        )
        
        response_text = response.content[0].text.strip()
        
    except Exception as e:
        print(f"[VoiceAI] Claude API error: {e}")
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
