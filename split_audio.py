"""
Split a single ElevenLabs MP3 containing 48 Aisha upsell sentences
into individual files UP_001.mp3 … UP_048.mp3 using silence detection.

Usage:
    python split_audio.py

If silence-based splitting doesn't produce exactly 48 segments,
falls back to equal-duration splitting (total_duration / 48).
"""

import os
from pathlib import Path
from pydub import AudioSegment
from pydub.silence import split_on_silence

SRC = Path("static/audio/ElevenLabs_Untitled_project.mp3")
OUT_DIR = Path("static/audio/wavs")
EXPECTED = 48


def silence_split(audio: AudioSegment) -> list[AudioSegment]:
    """Try splitting by silence with progressively relaxed parameters."""
    configs = [
        {"min_silence_len": 700, "silence_thresh": -40, "keep_silence": 250},
        {"min_silence_len": 500, "silence_thresh": -38, "keep_silence": 200},
        {"min_silence_len": 400, "silence_thresh": -36, "keep_silence": 200},
        {"min_silence_len": 600, "silence_thresh": -42, "keep_silence": 250},
        {"min_silence_len": 800, "silence_thresh": -45, "keep_silence": 300},
        {"min_silence_len": 1000, "silence_thresh": -45, "keep_silence": 300},
    ]
    for cfg in configs:
        chunks = split_on_silence(audio, **cfg)
        print(f"  Config {cfg} → {len(chunks)} chunks")
        if len(chunks) == EXPECTED:
            return chunks
    return []


def equal_split(audio: AudioSegment) -> list[AudioSegment]:
    """Fallback: split into 48 equal-duration segments."""
    chunk_len = len(audio) / EXPECTED
    chunks = []
    for i in range(EXPECTED):
        start = int(i * chunk_len)
        end = int((i + 1) * chunk_len)
        chunks.append(audio[start:end])
    return chunks


def main():
    if not SRC.exists():
        print(f"ERROR: Source file not found: {SRC}")
        print("Please upload ElevenLabs_Untitled_project.mp3 to static/audio/")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading {SRC} ...")
    audio = AudioSegment.from_mp3(str(SRC))
    print(f"Duration: {len(audio) / 1000:.1f}s")

    print("\n=== Attempting silence-based splitting ===")
    chunks = silence_split(audio)

    if len(chunks) != EXPECTED:
        print(f"\nSilence split gave {len(chunks)} chunks (need {EXPECTED}).")
        print("Falling back to equal-duration splitting.")
        chunks = equal_split(audio)

    print(f"\nExporting {len(chunks)} files ...")
    for i, chunk in enumerate(chunks, 1):
        out_path = OUT_DIR / f"UP_{i:03d}.mp3"
        chunk.export(str(out_path), format="mp3")
        print(f"  {out_path} ({len(chunk) / 1000:.1f}s)")

    print(f"\nDone! {len(chunks)} files saved to {OUT_DIR}/")


if __name__ == "__main__":
    main()
