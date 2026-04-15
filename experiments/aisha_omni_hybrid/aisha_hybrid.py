#!/usr/bin/env python3
"""
Aisha Hybrid (Path C) — Omni STT/LLM + ElevenLabs TTS.

Architecture:
  mic → Qwen3.5-Omni-Realtime (TEXT mode only) → JSON reply
      → menu_validator.validate_order_items()
      → ElevenLabs TTS (AFIFAH voice) → speakers
      → on confirm_order: Telegram to -4879870981

Omni is used for STT + response generation ONLY. Voice synthesis
is handed off to ElevenLabs so we keep the custom AFIFAH voice.

Usage:  python aisha_hybrid.py
Stop:   Ctrl+C
"""

# Make the repo root importable BEFORE anything else so we can pull in
# the production menu_validator + order_engine.
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import asyncio
import base64
import json
import math
import signal
import struct
import time

import pyaudio
import httpx
import websockets
import requests
from dotenv import load_dotenv

try:
    import audioop
except ImportError:
    import pyaudioop as audioop  # audioop-lts for Python 3.13+

# ── Config ────────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)  # so we can import order_engine / menu_validator

load_dotenv(os.path.join(REPO_ROOT, ".env"))

DASHSCOPE_KEY = os.getenv("DASHSCOPE_API_KEY", "")
ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "")  # AFIFAH voice id
TG_BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("HYBRID_TELEGRAM_CHAT_ID", "-4879870981")

WS_URL = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime?model=qwen3-omni-flash-realtime"
ELEVEN_STREAM_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=pcm_24000"

# Audio
OMNI_IN_RATE = 16000
ELEVEN_OUT_RATE = 24000
DEVICE_RATE = 44100
SAMPLE_WIDTH = 2
CHANNELS = 1
FORMAT = pyaudio.paInt16
MIC_CHUNK = DEVICE_RATE // 10         # 4410 @ 44.1kHz = 100ms

DEFAULT_MIC_INDEX = int(os.getenv("MIC_DEVICE_INDEX", "1"))
DEFAULT_SPK_INDEX = int(os.getenv("SPEAKER_DEVICE_INDEX", "3"))

PROMPT_FILE = os.path.join(os.path.dirname(__file__), "aisha_hybrid_system_prompt.txt")

# ── Menu validation ───────────────────────────────────────────────────────────
# Prefer production menu_validator if present; else fall back to inline check.

try:
    from menu_validator import validate_order_items as _validate_items
    from order_engine import MENU

    def validate_order(items: list[str]) -> dict:
        extracted = [{"matched_item": i, "quantity": 1, "confidence": 1.0,
                      "modifiers": []} for i in items]
        return _validate_items(extracted)

    VALIDATOR = f"LOADED {len(MENU)} items"
except Exception as e:
    from order_engine import MENU  # fallback — MENU dict only

    def validate_order(items: list[str]) -> dict:
        valid, invalid = [], []
        for it in items:
            key = it.lower().strip()
            if key in MENU:
                valid.append({"item_key": key, "price": MENU[key]["price"]})
            else:
                invalid.append({"original": it})
        return {"valid_items": valid, "invalid_items": invalid,
                "all_valid": len(invalid) == 0}

    VALIDATOR = f"inline-fallback ({type(e).__name__})"


# ── System prompt ─────────────────────────────────────────────────────────────

FALLBACK_PROMPT = """Kau adalah Aisha, pelayan virtual di Khulafa Bistro.
Jawab dalam Bahasa Melayu santai gaya mamak. Pendek je — max 2 ayat.

MENU TOP SELLERS:
roti canai RM1.50, roti telur RM2.50, nasi ayam RM7.52, nasi ayam sayur RM8.03,
nasi ayam bawang RM10.59, nasi goreng ayam RM10.50, nasi goreng kampung RM6.56,
mee goreng mamak RM6.00, maggi goreng RM6.00, maggi goreng telur mata RM7.50,
ayam goreng RM5.00, ayam tandoori RM8.50, naan biasa RM3.00,
naan mozzerella cheese RM7.00, teh RM1.70, teh ais RM2.60, teh o RM1.50,
teh o ais RM2.10, milo ais RM3.30, ais kosong RM0.30, air suam RM0.30,
limau ais RM2.57, teh o limau ais RM2.50, extra joss angur RM4.00,
nasi lemak bungkus RM2.60, telur mata RM1.50, telur masin RM1.50,
nasi putih RM2.33, roti bakar RM2.50, nasi ayam bawang sayur RM11.00.

RESPONSE FORMAT — always reply in EXACT JSON, nothing else:
{"items": ["nasi goreng daging"], "action": "add_items", "reply": "Nasi goreng daging satu!"}

Actions:
  - add_items: customer ordered items
  - confirm_order: customer said "tu je" / "cukup" / "dah" / "confirm" / "settle"
  - unclear: cannot understand, ask to repeat

CRITICAL — EXTRACT, DO NOT SUBSTITUTE:
  - Extract items EXACTLY as customer says them. Output the LITERAL words used.
  - NEVER substitute "daging" with "ayam". NEVER substitute "kambing" with "kampung".
  - NEVER swap ingredients for similar-sounding menu items.
  - If customer says "nasi goreng daging", items MUST be ["nasi goreng daging"],
    NOT ["nasi goreng ayam"]. The validator matches to the real menu separately.
  - When unsure, keep the customer's words verbatim — do not auto-correct.

Rules:
  - item names MUST be lowercase, use customer's literal words
  - "reply" is what Aisha says (spoken via TTS) — keep SHORT, max 2 ayat
  - no text outside the JSON
"""


def load_prompt() -> str:
    if os.path.isfile(PROMPT_FILE):
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return FALLBACK_PROMPT


# ── Audio I/O ─────────────────────────────────────────────────────────────────

def rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    return math.sqrt(sum(s * s for s in struct.unpack(f"<{n}h", pcm)) / n)


class MicCapture:
    """Capture at 44.1kHz, resample to 16kHz for Omni."""
    def __init__(self, device_index: int):
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=FORMAT, channels=CHANNELS, rate=DEVICE_RATE, input=True,
            input_device_index=device_index, frames_per_buffer=MIC_CHUNK,
        )
        self._rs = None

    def read(self) -> bytes:
        raw = self._stream.read(MIC_CHUNK, exception_on_overflow=False)
        out, self._rs = audioop.ratecv(
            raw, SAMPLE_WIDTH, CHANNELS, DEVICE_RATE, OMNI_IN_RATE, self._rs,
        )
        return out

    def close(self):
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()


class Speaker:
    """Accepts 24kHz PCM16 from ElevenLabs, resamples to 44.1kHz for playback."""
    def __init__(self, device_index: int):
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=FORMAT, channels=CHANNELS, rate=DEVICE_RATE, output=True,
            output_device_index=device_index, frames_per_buffer=DEVICE_RATE // 10,
        )
        self._rs = None

    def play(self, pcm_24k: bytes):
        if not pcm_24k:
            return
        out, self._rs = audioop.ratecv(
            pcm_24k, SAMPLE_WIDTH, CHANNELS, ELEVEN_OUT_RATE, DEVICE_RATE, self._rs,
        )
        self._stream.write(out)

    def close(self):
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()


# ── ElevenLabs TTS streaming (optional) ───────────────────────────────────────

TTS_ENABLED = bool(ELEVEN_KEY and ELEVEN_VOICE)


async def tts_stream_and_play(text: str, speaker: Speaker | None):
    """Stream PCM from ElevenLabs into speaker. If TTS disabled, print only."""
    if not TTS_ENABLED:
        print(f"\n[AISHA]: {text}\n")
        return

    url = ELEVEN_STREAM_URL.format(voice=ELEVEN_VOICE)
    headers = {"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.4},
    }

    t0 = time.monotonic()
    total = 0
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as r:
                if r.status_code != 200:
                    body = await r.aread()
                    print(f"[tts] ElevenLabs {r.status_code}: {body[:200]}")
                    return
                async for chunk in r.aiter_bytes(chunk_size=4800):
                    if chunk:
                        speaker.play(chunk)
                        total += len(chunk)
    except Exception as e:
        print(f"[tts] error: {e}")
        return

    dt = time.monotonic() - t0
    print(f"[tts] played {total} bytes in {dt:.2f}s")


# ── Telegram (optional) ───────────────────────────────────────────────────────

TELEGRAM_ENABLED = bool(TG_BOT)


def send_telegram(text: str):
    if not TELEGRAM_ENABLED:
        print("\n" + "=" * 60)
        print("  [TELEGRAM DISABLED — order would be sent to chat:", TG_CHAT, "]")
        print("=" * 60)
        print(text)
        print("=" * 60 + "\n")
        return
    url = f"https://api.telegram.org/bot{TG_BOT}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
        }, timeout=10)
        if resp.ok:
            print(f"[tg]  sent to {TG_CHAT}")
        else:
            print(f"[tg]  fail {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[tg]  error: {e}")


def format_order_for_telegram(order: list[dict]) -> str:
    lines = ["🔔 <b>NEW ORDER — Aisha Hybrid</b>", ""]
    total = 0.0
    for it in order:
        key = it["item_key"]
        price = it["price"]
        total += price
        lines.append(f"  • {key} — RM{price:.2f}")
    lines += ["", f"💰 <b>TOTAL: RM{total:.2f}</b>"]
    return "\n".join(lines)


# ── WebSocket session ─────────────────────────────────────────────────────────

def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of possibly noisy text."""
    text = text.strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


async def run(mic_idx: int, spk_idx: int):
    if not DASHSCOPE_KEY:
        print("ERROR: DASHSCOPE_API_KEY not set")
        sys.exit(1)

    print(f"[init] validator   : {VALIDATOR}")
    print(f"[init] elevenlabs  : {'ON  (voice=' + ELEVEN_VOICE + ')' if TTS_ENABLED else 'OFF (text-only output)'}")
    print(f"[init] telegram    : {'ON  (chat=' + str(TG_CHAT) + ')' if TELEGRAM_ENABLED else 'OFF (orders print to terminal)'}")
    print(f"[init] mic device  : {mic_idx} @ {DEVICE_RATE}Hz → resample {OMNI_IN_RATE}Hz")
    if TTS_ENABLED:
        print(f"[init] spk device  : {spk_idx} @ {DEVICE_RATE}Hz ← ElevenLabs {ELEVEN_OUT_RATE}Hz")
    else:
        print("[init] spk device  : (none — TTS disabled)")

    prompt = load_prompt()
    mic = MicCapture(mic_idx)
    spk = Speaker(spk_idx) if TTS_ENABLED else None
    cart: list[dict] = []

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, lambda s, f: stop.set())
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)

    headers = {"Authorization": f"Bearer {DASHSCOPE_KEY}"}

    try:
        async with websockets.connect(WS_URL, additional_headers=headers) as ws:
            print("[ws] connected")

            # TEXT-ONLY session — no voice output from Omni
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["text"],
                    "instructions": prompt,
                    "input_audio_format": "pcm16",
                    "input_audio_transcription": {"model": "gummy-realtime-v1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "silence_duration_ms": 700,
                        "prefix_padding_ms": 300,
                    },
                },
            }))
            print("[ws] session.update sent (text-only)\n")

            async def stream_mic():
                last_log = time.monotonic()
                bytes_sent = 0
                while not stop.is_set():
                    pcm = await loop.run_in_executor(None, mic.read)
                    try:
                        await ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(pcm).decode("ascii"),
                        }))
                        bytes_sent += len(pcm)
                    except websockets.ConnectionClosed:
                        break
                    now = time.monotonic()
                    if now - last_log >= 2.0:
                        mark = "*" if rms(pcm) > 500 else " "
                        print(f"[mic] {bytes_sent} bytes {mark}")
                        last_log = now

            async def handle_reply(text: str):
                parsed = extract_json(text)
                if parsed is None:
                    print(f"[warn] could not parse JSON: {text[:200]}")
                    return
                action = parsed.get("action", "")
                reply = (parsed.get("reply") or "").strip()
                items = parsed.get("items") or []
                print(f"[json] action={action}  items={items}  reply={reply!r}")

                if reply:
                    await tts_stream_and_play(reply, spk)

                if action == "add_items" and items:
                    result = validate_order(items)
                    cart.extend(result["valid_items"])
                    if result["invalid_items"]:
                        print(f"[validator] dropped: {result['invalid_items']}")

                if action == "confirm_order":
                    if not cart:
                        print("[order] nothing in cart")
                        return
                    msg = format_order_for_telegram(cart)
                    print("[order] final:\n" + msg)
                    send_telegram(msg)
                    cart.clear()

            async def receive():
                text_buf = []
                async for raw in ws:
                    if stop.is_set():
                        break
                    try:
                        evt = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    etype = evt.get("type", "?")

                    if etype == "response.text.delta":
                        text_buf.append(evt.get("delta", ""))
                    elif etype == "response.text.done":
                        full = "".join(text_buf) or evt.get("text", "")
                        text_buf.clear()
                        print(f"\n[Aisha] {full}")
                        asyncio.create_task(handle_reply(full))
                    elif etype == "conversation.item.input_audio_transcription.completed":
                        print(f"[You]   {evt.get('transcript', '')}")
                    elif etype == "input_audio_buffer.speech_started":
                        print("[vad]   speech_started")
                    elif etype == "input_audio_buffer.speech_stopped":
                        print("[vad]   speech_stopped")
                    elif etype == "error":
                        print(f"[ERROR] {evt.get('error')}")
                    elif etype in ("session.created", "session.updated",
                                   "response.created", "response.done"):
                        print(f"[evt]   {etype}")

            mic_task = asyncio.create_task(stream_mic())
            recv_task = asyncio.create_task(receive())
            await stop.wait()
            mic_task.cancel()
            recv_task.cancel()

    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}")
    finally:
        mic.close()
        if spk is not None:
            spk.close()
        print("\n[exit] Bye!")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Aisha Hybrid — Omni (text) + ElevenLabs (voice)")
    print("  Ctrl+C to exit")
    print("=" * 60)
    asyncio.run(run(DEFAULT_MIC_INDEX, DEFAULT_SPK_INDEX))
