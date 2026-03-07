"""
Split ElevenLabs MP3 files containing Aisha upsell sentences
into individual files using silence detection.

Batch 1: ElevenLabs_Untitled_project.mp3 → UP_001.mp3 … UP_048.mp3 (48 food upsells)
Batch 2: ElevenLabs_Untitled_project (1).mp3 → UP_049.mp3 … UP_112.mp3 (64 drink/combo upsells)

Usage:
    python split_audio.py
    python split_audio.py --batch 2

If silence-based splitting doesn't produce the exact expected count,
uses smart merging/splitting of chunks to reach the target.
"""

import os
import argparse
from pathlib import Path
from pydub import AudioSegment
from pydub.silence import split_on_silence, detect_silence

OUT_DIR = Path("static/audio/wavs")

BATCHES = {
    1: {
        "src": OUT_DIR / "ElevenLabs_Untitled_project.mp3",
        "expected": 48,
        "start_index": 1,
    },
    2: {
        "src": OUT_DIR / "ElevenLabs_Untitled_project (1).mp3",
        "expected": 64,
        "start_index": 49,
    },
}


def silence_split(audio: AudioSegment, expected: int) -> list[AudioSegment]:
    """Try splitting by silence with progressively relaxed parameters."""
    configs = [
        {"min_silence_len": 410, "silence_thresh": -36, "keep_silence": 200},
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
        if len(chunks) == expected:
            return chunks
    return []


def smart_split(audio: AudioSegment, expected: int) -> list[AudioSegment]:
    """Use silence detection + smart merging to get exact chunk count."""
    total_ms = len(audio)
    silences = detect_silence(audio, min_silence_len=400, silence_thresh=-36, seek_step=10)
    split_points = [0]
    for start, end in silences:
        split_points.append((start + end) // 2)
    split_points.append(total_ms)

    merged = [(split_points[i], split_points[i+1]) for i in range(len(split_points) - 1)]
    print(f"  Initial chunks from silence: {len(merged)}")

    # Merge small chunks (< 1.5s)
    changed = True
    while changed and len(merged) > expected:
        changed = False
        new_merged = []
        for start, end in merged:
            if end - start < 1500 and new_merged and len(merged) > expected:
                prev_start, _ = new_merged[-1]
                new_merged[-1] = (prev_start, end)
                changed = True
            else:
                new_merged.append((start, end))
        merged = new_merged

    # Merge shortest adjacent pairs until target
    while len(merged) > expected:
        min_dur = float('inf')
        min_idx = 0
        for i, (s, e) in enumerate(merged):
            if e - s < min_dur:
                min_dur = e - s
                min_idx = i
        if min_idx == 0:
            merged[1] = (merged[0][0], merged[1][1])
            merged.pop(0)
        elif min_idx == len(merged) - 1:
            merged[-2] = (merged[-2][0], merged[-1][1])
            merged.pop(-1)
        else:
            left_dur = merged[min_idx-1][1] - merged[min_idx-1][0]
            right_dur = merged[min_idx+1][1] - merged[min_idx+1][0]
            if left_dur <= right_dur:
                merged[min_idx-1] = (merged[min_idx-1][0], merged[min_idx][1])
            else:
                merged[min_idx+1] = (merged[min_idx][0], merged[min_idx+1][1])
            merged.pop(min_idx)

    # Split longest chunks until target
    while len(merged) < expected:
        max_dur = 0
        max_idx = 0
        for i, (s, e) in enumerate(merged):
            if e - s > max_dur:
                max_dur = e - s
                max_idx = i
        s, e = merged[max_idx]
        mid = (s + e) // 2
        merged[max_idx] = (s, mid)
        merged.insert(max_idx + 1, (mid, e))

    return [audio[s:e] for s, e in merged]


def equal_split(audio: AudioSegment, expected: int) -> list[AudioSegment]:
    """Fallback: split into equal-duration segments."""
    chunk_len = len(audio) / expected
    return [audio[int(i * chunk_len):int((i + 1) * chunk_len)] for i in range(expected)]


def split_batch(batch_num: int):
    batch = BATCHES[batch_num]
    src = batch["src"]
    expected = batch["expected"]
    start_idx = batch["start_index"]

    if not src.exists():
        print(f"ERROR: Source file not found: {src}")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Loading {src} ...")
    audio = AudioSegment.from_mp3(str(src))
    print(f"Duration: {len(audio) / 1000:.1f}s")

    print("\n=== Attempting silence-based splitting ===")
    chunks = silence_split(audio, expected)

    if len(chunks) != expected:
        print(f"\nExact silence split failed. Using smart merge/split...")
        chunks = smart_split(audio, expected)

    if len(chunks) != expected:
        print(f"\nSmart split gave {len(chunks)} (need {expected}). Falling back to equal split.")
        chunks = equal_split(audio, expected)

    print(f"\nExporting {len(chunks)} files ...")
    for i, chunk in enumerate(chunks):
        idx = start_idx + i
        out_path = OUT_DIR / f"UP_{idx:03d}.mp3"
        chunk.export(str(out_path), format="mp3")
        print(f"  {out_path} ({len(chunk) / 1000:.1f}s)")

    print(f"\nDone! {len(chunks)} files saved to {OUT_DIR}/")


def main():
    parser = argparse.ArgumentParser(description="Split ElevenLabs MP3 into individual upsell clips")
    parser.add_argument("--batch", type=int, choices=[1, 2], default=None,
                        help="Which batch to split (1 or 2). Splits both if omitted.")
    args = parser.parse_args()

    if args.batch:
        split_batch(args.batch)
    else:
        for b in [1, 2]:
            if BATCHES[b]["src"].exists():
                print(f"\n{'='*50}")
                print(f"BATCH {b}")
                print(f"{'='*50}")
                split_batch(b)


if __name__ == "__main__":
    main()
