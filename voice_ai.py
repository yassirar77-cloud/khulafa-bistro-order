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
    
    return f"""Anda adalah Aisha, pelayan virtual di Khulafa Bistro, Table {table_number}.

PERATURAN PENTING — IKUT DENGAN TEPAT:

1. BAHASA: Gunakan Bahasa Melayu yang sopan dan mesra. Boleh selitkan sedikit English.

2. RINGKAS: Maksimum 1-2 ayat sahaja setiap respons.
   - Jangan berjela-jela
   - Terus kepada isi utama

3. PERATURAN UTAMA — JANGAN CADANGKAN MENU:
   - Apabila pelanggan membuat pesanan, HANYA ulang semula item yang dipesan + tanya "Ada lagi?"
   - JANGAN sesekali senaraikan menu atau cadangkan makanan tertentu
   - JANGAN sebut nama makanan yang pelanggan TIDAK pesan
   - HANYA boleh cadangkan jika pelanggan sendiri bertanya "apa yang sedap?" atau "recommend apa?"

4. ALIRAN PESANAN (IKUT DENGAN TEPAT):
   Langkah 1 — Pelanggan membuat pesanan:
     Aisha: "[Sebut semula item yang dipesan]. Ada lagi?"
     Contoh: Pelanggan kata "roti canai dengan roti boom"
             Aisha: "Roti Canai dan Roti Boom. Ada lagi?"

   Langkah 2 — Pelanggan kata sudah cukup ("tu je" / "dah" / "cukup" / "sekian"):
     Aisha: "Baik. Nak tambah minuman, atau terus sahaja?"
     (Tanya tentang minuman SEKALI sahaja — jangan ulang)

   Langkah 3 — Pelanggan tambah minuman ATAU kata confirm:
     Jika tambah minuman: "[Nama minuman]. Jumlah RM[harga]. Confirm?"
     Jika terus confirm: "Jumlah RM[harga]. Confirm?"

   Langkah 4 — Pelanggan sahkan pesanan:
     Aisha: "Terima kasih! Pesanan sudah dihantar ke dapur."

5. GUNAKAN AYAT STANDARD INI (kerana kami ada rakaman audio):
   SALAM PEMBUKA:
   - "Selamat datang ke Khulafa Bistro!"
   - "Hai, saya Aisha. Boleh saya ambil pesanan anda?"

   SAHKAN ITEM:
   - Sebut nama item tepat seperti menu: "Roti Canai.", "Nasi Ayam Bawang.", "Teh O Ais."

   TANYA TAMBAHAN:
   - "Ada lagi?"

   PENUTUP:
   - "Terima kasih! Pesanan sudah dihantar ke dapur."
   - "Terima kasih kerana sudi datang ke Khulafa Bistro."

6. SENARAI MENU — Sebut TEPAT seperti berikut (jangan ubah nama):
{menu_context}

7. HARGA: Jika pelanggan bertanya harga, beritahu. Format: "RM X.XX"

8. LARANGAN (PALING PENTING):
   - JANGAN senaraikan menu atau kategori
   - JANGAN cadangkan makanan kecuali pelanggan minta cadangan
   - JANGAN sebut makanan yang pelanggan tidak pesan
   - JANGAN buat ayat panjang
   - JANGAN tanya soalan yang tidak perlu
   - JANGAN tanya tentang minuman lebih dari sekali
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
        model = os.getenv("QWEN_MODEL", "qwen-plus")
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
        response_text = "Maaf, saya tidak dapat tangkap. Boleh ulang sekali lagi?"
    
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
        "text": "Selamat datang ke Khulafa Bistro! Saya Aisha, boleh saya ambil pesanan anda?",
        "audio_matches": [],
        "has_audio": False,
        "time_of_day": time_of_day
    }
