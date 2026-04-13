#!/usr/bin/env python3
"""
Standalone terminal test for Qwen3.5-Omni-Realtime via WebSocket.
Captures mic audio, streams to Omni, plays voice response, prints transcript.

Usage:  python test_voice.py
Stop:   Ctrl+C
"""

import asyncio
import base64
import json
import os
import signal
import struct
import sys
import uuid

import pyaudio
import websockets
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(REPO_ROOT, ".env"))

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
WS_URL = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
MODEL = "qwen3.5-omni-realtime"

RATE = 24000       # 24 kHz mono PCM16 — Omni default
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 2400       # 100 ms frames at 24 kHz

PROMPT_FILE = os.path.join(REPO_ROOT, "aisha_omni_system_prompt.txt")
FALLBACK_PROMPT = (
    "Kau adalah Aisha, pelayan virtual di Khulafa Bistro. "
    "Jawab dalam Bahasa Melayu santai. Pendek je — max 2 ayat. "
    "Top menu: Roti Canai RM1.50, Teh O Ais RM2.10, Nasi Ayam RM7.52, "
    "Milo Ais RM3.30, Mee Goreng Mamak RM6.00, Maggi Goreng RM6.00."
)


def load_system_prompt() -> str:
    if os.path.isfile(PROMPT_FILE):
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return FALLBACK_PROMPT


# ── Audio helpers ─────────────────────────────────────────────────────────────

class AudioPlayer:
    """Plays raw PCM16-24kHz chunks via PyAudio."""

    def __init__(self):
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=FORMAT, channels=CHANNELS, rate=RATE, output=True,
            frames_per_buffer=CHUNK,
        )

    def play(self, pcm_bytes: bytes):
        self._stream.write(pcm_bytes)

    def close(self):
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()


class MicCapture:
    """Captures mic audio as PCM16-24kHz chunks."""

    def __init__(self):
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=FORMAT, channels=CHANNELS, rate=RATE, input=True,
            frames_per_buffer=CHUNK,
        )

    def read_chunk(self) -> bytes:
        return self._stream.read(CHUNK, exception_on_overflow=False)

    def close(self):
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()


# ── WebSocket session ─────────────────────────────────────────────────────────

async def run_session():
    if not API_KEY:
        print("ERROR: DASHSCOPE_API_KEY not found in .env")
        sys.exit(1)

    system_prompt = load_system_prompt()
    print(f"[init] System prompt loaded ({len(system_prompt)} chars)")
    print(f"[init] Connecting to {MODEL} ...")

    headers = {
        "Authorization": f"bearer {API_KEY}",
    }

    player = AudioPlayer()
    mic = MicCapture()
    stop = asyncio.Event()

    # Handle Ctrl+C
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        async with websockets.connect(WS_URL, additional_headers=headers) as ws:
            # ── 1. Send session.update to configure the model ─────────────
            session_update = {
                "type": "session.update",
                "session": {
                    "model": MODEL,
                    "modalities": ["text", "audio"],
                    "instructions": system_prompt,
                    "voice": "Cherry",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "turn_detection": {
                        "type": "server_vad",
                        "silence_duration_ms": 800,
                    },
                },
            }
            await ws.send(json.dumps(session_update))
            print("[init] Session config sent. Speak into your mic!\n")

            # ── 2. Mic streaming task ─────────────────────────────────────
            async def stream_mic():
                while not stop.is_set():
                    pcm = await loop.run_in_executor(None, mic.read_chunk)
                    audio_b64 = base64.b64encode(pcm).decode("ascii")
                    msg = {
                        "type": "input_audio_buffer.append",
                        "audio": audio_b64,
                    }
                    try:
                        await ws.send(json.dumps(msg))
                    except websockets.ConnectionClosed:
                        break

            # ── 3. Receive events task ────────────────────────────────────
            async def receive_events():
                transcript_parts = []
                async for raw in ws:
                    if stop.is_set():
                        break
                    try:
                        evt = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    etype = evt.get("type", "")

                    # Audio delta — play it
                    if etype == "response.audio.delta":
                        audio_b64 = evt.get("delta", "")
                        if audio_b64:
                            pcm = base64.b64decode(audio_b64)
                            player.play(pcm)

                    # Text / transcript delta — accumulate
                    elif etype == "response.audio_transcript.delta":
                        chunk = evt.get("delta", "")
                        if chunk:
                            print(chunk, end="", flush=True)
                            transcript_parts.append(chunk)

                    # Transcript done
                    elif etype == "response.audio_transcript.done":
                        transcript = evt.get("transcript", "".join(transcript_parts))
                        print(f"\n[Aisha] {transcript}\n")
                        transcript_parts.clear()

                    # Input transcript (what user said)
                    elif etype == "conversation.item.input_audio_transcription.completed":
                        user_text = evt.get("transcript", "")
                        if user_text:
                            print(f"[You]   {user_text}")

                    # Errors
                    elif etype == "error":
                        print(f"[error] {evt.get('error', evt)}")

                    # Session created / updated
                    elif etype in ("session.created", "session.updated"):
                        print(f"[{etype}] OK")

            # ── Run both tasks until Ctrl+C ───────────────────────────────
            mic_task = asyncio.create_task(stream_mic())
            recv_task = asyncio.create_task(receive_events())
            await stop.wait()
            mic_task.cancel()
            recv_task.cancel()

    except websockets.InvalidStatusCode as e:
        print(f"[error] WebSocket rejected: {e}")
    except Exception as e:
        print(f"[error] {e}")
    finally:
        mic.close()
        player.close()
        print("\n[exit] Bye!")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  Khulafa Bistro — Aisha Omni Voice Test")
    print("  Ctrl+C to exit")
    print("=" * 50)
    asyncio.run(run_session())
