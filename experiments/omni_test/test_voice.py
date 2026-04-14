#!/usr/bin/env python3
"""
Standalone terminal test for Qwen3.5-Omni-Realtime via WebSocket.
Captures mic audio, streams to Omni, plays voice response, prints transcript.

Usage:  python test_voice.py
Stop:   Ctrl+C

Device selection:
  - Set MIC_DEVICE_INDEX / SPEAKER_DEVICE_INDEX in .env, or
  - Pick interactively when prompted.
  - Defaults: input=1 (Microphone Array Realtek), output=3 (Speakers Realtek)

Audio format (Omni spec):
  - Input:  16kHz, 16-bit PCM, mono, base64-encoded
  - Output: 24kHz, 16-bit PCM, mono
"""

import asyncio
import base64
import json
import math
import os
import signal
import struct
import sys
import time

import pyaudio
import websockets
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(REPO_ROOT, ".env"))

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
WS_URL = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime?model=qwen3-omni-flash-realtime"
MODEL = "qwen3.5-omni-realtime"

# Omni spec: input is 16kHz, output is 24kHz, both PCM16 mono
RATE_IN = 16000
RATE_OUT = 24000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK_IN = 1600          # 100 ms frames at 16 kHz
CHUNK_OUT = 2400         # 100 ms frames at 24 kHz

DEFAULT_MIC_INDEX = 1       # Microphone Array (Realtek)
DEFAULT_SPEAKER_INDEX = 3   # Speakers (Realtek)

SILENCE_THRESHOLD = 500     # RMS above this = audible speech

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


# ── Device selection ──────────────────────────────────────────────────────────

def list_audio_devices():
    pa = pyaudio.PyAudio()
    count = pa.get_device_count()
    print(f"\n{'='*60}")
    print(f"  Audio Devices ({count} found)")
    print(f"{'='*60}")
    inputs, outputs = [], []
    for i in range(count):
        info = pa.get_device_info_by_index(i)
        name = info.get("name", "Unknown")
        max_in = info.get("maxInputChannels", 0)
        max_out = info.get("maxOutputChannels", 0)
        direction = []
        if max_in > 0:
            direction.append("IN")
            inputs.append(i)
        if max_out > 0:
            direction.append("OUT")
            outputs.append(i)
        tag = "/".join(direction) if direction else "---"
        print(f"  [{i:2d}] ({tag:7s})  {name}")
    print(f"{'='*60}")
    pa.terminate()
    return inputs, outputs


def pick_device(direction: str, env_var: str, default: int, valid_indices: list) -> int:
    env_val = os.getenv(env_var)
    if env_val is not None:
        idx = int(env_val)
        print(f"  {direction} device from {env_var}: [{idx}]")
        return idx
    prompt = f"  Pick {direction} device index [{default}]: "
    raw = input(prompt).strip()
    if raw == "":
        return default
    idx = int(raw)
    if idx not in valid_indices:
        print(f"  WARNING: device {idx} may not support {direction}")
    return idx


# ── Audio helpers ─────────────────────────────────────────────────────────────

def rms(pcm_bytes: bytes) -> float:
    n = len(pcm_bytes) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm_bytes)
    return math.sqrt(sum(s * s for s in samples) / n)


class AudioPlayer:
    """Plays raw PCM16-24kHz chunks via PyAudio."""
    def __init__(self, device_index: int):
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=FORMAT, channels=CHANNELS, rate=RATE_OUT, output=True,
            output_device_index=device_index,
            frames_per_buffer=CHUNK_OUT,
        )
        self.device_index = device_index

    def play(self, pcm_bytes: bytes):
        self._stream.write(pcm_bytes)

    def close(self):
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()


class MicCapture:
    """Captures mic audio as PCM16-16kHz chunks."""
    def __init__(self, device_index: int):
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=FORMAT, channels=CHANNELS, rate=RATE_IN, input=True,
            input_device_index=device_index,
            frames_per_buffer=CHUNK_IN,
        )
        self.device_index = device_index

    def read_chunk(self) -> bytes:
        return self._stream.read(CHUNK_IN, exception_on_overflow=False)

    def close(self):
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()


# ── WebSocket session ─────────────────────────────────────────────────────────

async def run_session(mic_idx: int, spk_idx: int):
    if not API_KEY:
        print("ERROR: DASHSCOPE_API_KEY not found in .env")
        sys.exit(1)

    system_prompt = load_system_prompt()
    print(f"[init] System prompt loaded ({len(system_prompt)} chars)")

    player = AudioPlayer(spk_idx)
    mic = MicCapture(mic_idx)
    print(f"[init] Listening on device {mic_idx} @ {RATE_IN}Hz mono PCM16")
    print(f"[init] Playing on device {spk_idx} @ {RATE_OUT}Hz mono PCM16")
    print(f"[init] Connecting to {WS_URL}")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
    }

    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, lambda s, f: stop.set())
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)

    try:
        async with websockets.connect(WS_URL, additional_headers=headers) as ws:
            print("[ws] connected")

            # ── 1. session.update — server VAD auto-commits + auto-creates response
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": system_prompt,
                    "voice": "Cherry",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": "gummy-realtime-v1",
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "silence_duration_ms": 700,
                        "prefix_padding_ms": 300,
                    },
                },
            }
            await ws.send(json.dumps(session_update))
            print(f"[send] session.update  vad=server_vad threshold=0.5 silence=700ms")
            print("[init] Speak into your mic!\n")

            # ── 2. Mic streaming task (no commit/response.create — server VAD handles it)
            bytes_sent = 0
            last_log = time.monotonic()

            async def stream_mic():
                nonlocal bytes_sent, last_log
                while not stop.is_set():
                    pcm = await loop.run_in_executor(None, mic.read_chunk)
                    level = rms(pcm)
                    audio_b64 = base64.b64encode(pcm).decode("ascii")
                    msg = {
                        "type": "input_audio_buffer.append",
                        "audio": audio_b64,
                    }
                    try:
                        await ws.send(json.dumps(msg))
                        bytes_sent += len(pcm)
                    except websockets.ConnectionClosed:
                        print("[ws] closed during send")
                        break

                    now = time.monotonic()
                    if now - last_log >= 1.0:
                        marker = "*" if level > SILENCE_THRESHOLD else " "
                        print(f"[mic] sent {bytes_sent} bytes  rms={level:6.0f} {marker}")
                        last_log = now

            # ── 3. Receive events task
            async def receive_events():
                transcript_parts = []
                async for raw in ws:
                    if stop.is_set():
                        break
                    try:
                        evt = json.loads(raw)
                    except json.JSONDecodeError:
                        print(f"[recv] non-JSON: {raw[:120]}")
                        continue

                    etype = evt.get("type", "?")

                    # Always log event type
                    if etype not in ("response.audio.delta", "response.audio_transcript.delta"):
                        print(f"[evt] {etype}")

                    if etype == "response.audio.delta":
                        audio_b64 = evt.get("delta", "")
                        if audio_b64:
                            pcm = base64.b64decode(audio_b64)
                            print(f"[recv] got audio chunk ({len(pcm)} bytes)")
                            player.play(pcm)

                    elif etype == "response.audio_transcript.delta":
                        chunk = evt.get("delta", "")
                        if chunk:
                            transcript_parts.append(chunk)
                            print(f"[recv] got text: {chunk!r}")

                    elif etype == "response.audio_transcript.done":
                        transcript = evt.get("transcript", "".join(transcript_parts))
                        print(f"\n[Aisha] {transcript}\n")
                        transcript_parts.clear()

                    elif etype == "conversation.item.input_audio_transcription.completed":
                        user_text = evt.get("transcript", "")
                        print(f"[You]   {user_text}")

                    elif etype == "input_audio_buffer.speech_started":
                        print("[vad] speech_started")

                    elif etype == "input_audio_buffer.speech_stopped":
                        print("[vad] speech_stopped")

                    elif etype == "input_audio_buffer.committed":
                        print(f"[vad] buffer committed (item_id={evt.get('item_id')})")

                    elif etype == "response.created":
                        print(f"[resp] created (id={evt.get('response', {}).get('id')})")

                    elif etype == "response.done":
                        status = evt.get("response", {}).get("status")
                        print(f"[resp] done (status={status})")
                        if status == "failed":
                            print(f"       details: {evt.get('response')}")

                    elif etype == "error":
                        print(f"[ERROR] {json.dumps(evt.get('error', evt), ensure_ascii=False)}")

                    elif etype in ("session.created", "session.updated"):
                        sess = evt.get("session", {})
                        print(f"       voice={sess.get('voice')} "
                              f"in_fmt={sess.get('input_audio_format')} "
                              f"out_fmt={sess.get('output_audio_format')}")

            mic_task = asyncio.create_task(stream_mic())
            recv_task = asyncio.create_task(receive_events())
            await stop.wait()
            mic_task.cancel()
            recv_task.cancel()

    except websockets.InvalidStatusCode as e:
        print(f"[error] WebSocket rejected: {e}")
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}")
    finally:
        mic.close()
        player.close()
        print("\n[exit] Bye!")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Khulafa Bistro — Aisha Omni Voice Test (debug v3)")
    print("  Ctrl+C to exit")
    print("=" * 60)

    input_devs, output_devs = list_audio_devices()

    print("\n  Device Selection")
    print("  (set MIC_DEVICE_INDEX / SPEAKER_DEVICE_INDEX in .env to skip)")
    mic_idx = pick_device("INPUT", "MIC_DEVICE_INDEX", DEFAULT_MIC_INDEX, input_devs)
    spk_idx = pick_device("OUTPUT", "SPEAKER_DEVICE_INDEX", DEFAULT_SPEAKER_INDEX, output_devs)
    print()

    asyncio.run(run_session(mic_idx, spk_idx))
