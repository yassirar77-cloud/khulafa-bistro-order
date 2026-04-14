# Aisha Omni Voice Test

Standalone terminal test for **Qwen3.5-Omni-Realtime** WebSocket API.
Captures mic → streams to Omni → plays voice response → prints transcript.

## Prerequisites (WSL Ubuntu)

```bash
# System deps for PyAudio
sudo apt update && sudo apt install -y portaudio19-dev python3-pyaudio pulseaudio

# Start PulseAudio (WSL needs this)
pulseaudio --start 2>/dev/null || true
```

## Install

```bash
cd experiments/omni_test
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure

Add your API key to `.env` in the repo root:

```
DASHSCOPE_API_KEY=sk-your-key-here

# Optional — device & voice overrides
MIC_DEVICE_INDEX=1
SPEAKER_DEVICE_INDEX=3
OMNI_VOICE=Ethan
```

### Available voices

Default is **Ethan** (English male). Override with `OMNI_VOICE` env var:

| Voice   | Notes                      |
|---------|----------------------------|
| Cherry  | Chinese female             |
| Ethan   | English male (default)     |
| Serena  | English female             |
| Chelsie | Chinese female, warm tone  |
| Dylan   | English male, casual       |
| Jada    | English female, energetic  |
| Sunny   | English female, bright     |

Quick switch:
```bash
OMNI_VOICE=Serena python test_voice.py
```

## Run

```bash
source .venv/bin/activate
python test_voice.py
```

Speak into your mic. Aisha replies in voice + transcript prints in terminal.
Press **Ctrl+C** to exit.

## Files

| File | Purpose |
|------|---------|
| `test_voice.py` | WebSocket client — mic capture, audio playback, transcript display |
| `requirements.txt` | Python dependencies |
| `../../aisha_omni_system_prompt.txt` | Aisha persona + top 30 menu items (repo root) |
