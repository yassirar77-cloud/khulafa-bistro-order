#!/usr/bin/env python3
"""
Simple mic test: record 5 seconds from device 1, save to test.wav,
play back on device 3. Prints volume level every 0.5s.

Usage: python mic_test.py
"""

import math
import struct
import wave

import pyaudio

RATE = 24000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 2400          # 100ms frames
RECORD_SECONDS = 5
WAV_FILE = "test.wav"

MIC_INDEX = 1         # Microphone Array (Realtek)
SPEAKER_INDEX = 3     # Speakers (Realtek)


def rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm)
    return math.sqrt(sum(s * s for s in samples) / n)


def record():
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=FORMAT, channels=CHANNELS, rate=RATE, input=True,
        input_device_index=MIC_INDEX, frames_per_buffer=CHUNK,
    )
    print(f"Recording {RECORD_SECONDS}s from device {MIC_INDEX} ...")

    frames = []
    chunks_per_half_sec = RATE // CHUNK // 2  # how many chunks in 0.5s
    for i in range(RATE // CHUNK * RECORD_SECONDS):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
        if i % chunks_per_half_sec == 0:
            level = rms(data)
            bar = "#" * min(int(level / 100), 50)
            print(f"  [{i * CHUNK / RATE:5.1f}s]  RMS: {level:6.0f}  {bar}")

    stream.stop_stream()
    stream.close()
    pa.terminate()

    with wave.open(WAV_FILE, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
    print(f"Saved to {WAV_FILE}")
    return frames


def playback(frames):
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=FORMAT, channels=CHANNELS, rate=RATE, output=True,
        output_device_index=SPEAKER_INDEX, frames_per_buffer=CHUNK,
    )
    print(f"Playing back on device {SPEAKER_INDEX} ...")
    for f in frames:
        stream.write(f)
    stream.stop_stream()
    stream.close()
    pa.terminate()
    print("Done.")


if __name__ == "__main__":
    data = record()
    playback(data)
