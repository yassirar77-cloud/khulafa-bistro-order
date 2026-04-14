# Aisha Hybrid — Path C

Experimental Aisha flow that keeps the custom **AFIFAH** voice while getting
cheaper, faster intent from Qwen3.5-Omni-Realtime.

```
  mic  ─►  Omni-Realtime (TEXT mode)  ─►  JSON reply
                                              │
                              menu_validator.py │
                                              ▼
                            ElevenLabs stream TTS (AFIFAH)
                                              ▼
                                          speakers
                                              │
                 on confirm_order: Telegram ─►
```

## What's different from Path A

| Component | Path A (terminal test) | Path C (this folder) |
|-----------|------------------------|----------------------|
| STT       | Omni                   | Omni                 |
| LLM       | Omni                   | Omni                 |
| **TTS**   | Omni voice (Ethan)     | **ElevenLabs AFIFAH** |
| Validation| none                   | `menu_validator.py`  |
| Telegram  | none                   | chat `-4879870981`   |

Omni is started with `modalities: ["text"]` so it never generates audio.
Its JSON `reply` is streamed to ElevenLabs `/v1/text-to-speech/{voice}/stream`
with `output_format=pcm_24000` so we can play raw PCM directly.

## Install (WSL Ubuntu / Windows)

```bash
# System deps (WSL)
sudo apt update && sudo apt install -y portaudio19-dev python3-pyaudio pulseaudio

cd experiments/aisha_omni_hybrid
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configure

Add to `.env` in the repo root:

```
DASHSCOPE_API_KEY=sk-...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=<AFIFAH voice id>
TELEGRAM_BOT_TOKEN=...

# Optional overrides
MIC_DEVICE_INDEX=1
SPEAKER_DEVICE_INDEX=3
HYBRID_TELEGRAM_CHAT_ID=-4879870981
```

## Run

```bash
python aisha_hybrid.py
```

Speak into your mic. Omni transcribes + replies in JSON; ElevenLabs speaks
the `reply` field in AFIFAH voice. When you say *"tu je"* / *"settle"*,
the order is validated via `menu_validator.py` and posted to Telegram chat
`-4879870981`.

Press **Ctrl+C** to exit.

## Files

| File | Purpose |
|------|---------|
| `aisha_hybrid.py` | Main script (async WS + TTS + Telegram) |
| `aisha_hybrid_system_prompt.txt` | Aisha persona + top 30 menu + JSON spec |
| `requirements.txt` | Python deps |
