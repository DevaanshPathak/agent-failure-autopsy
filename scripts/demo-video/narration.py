"""Narration for the demo video: one line per scene, spoken by Kokoro, checked with Whisper.
Usage: python narration.py <voice> <out-dir>   (voice: hm_omega | hm_psi)"""

import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel
from kokoro_onnx import Kokoro

SCENES = {
    "intro": (
        "Web agents are great at doing the work. But when they fail, they usually fail quietly. "
        "They say done, and hand you nothing, or the wrong answer. Agent Failure Autopsy is a "
        "reliability layer for TinyFish agents. It catches exactly that."
    ),
    "cards": (
        "You give it a page, a goal, and a check the answer has to pass. To make that easy, there "
        "are prepared autopsies: test pages we built to trip agents on purpose, plus a few real "
        "websites. One click, and the run is live."
    ),
    "run1": (
        "Let's run the chart that only loads after a click. First, the cheapest rung: a plain "
        "TinyFish fetch, which costs nothing. Our own verifier checks the answer, and it fails, "
        "because the 2019 data isn't on the page yet. The diagnoser names the failure, needs "
        "interaction, and points to the exact step. So the run climbs to a real browser agent, "
        "and you can watch it live as it opens the 2019 tab and reads the table. This time the "
        "answer passes the check. Verified, for five credits."
    ),
    "run2": (
        "Some failures can't be fixed, and the tool knows it. This account page redirects to a "
        "login. It's caught on the first, free rung, so the run stops right there, with an honest "
        "reason, for zero credits."
    ),
    "run3": (
        "This page blocks bots. The fetch gets a four oh three, so the ladder skips straight to "
        "the top rung: a stealth browser behind a proxy. It's still denied, so after four credits "
        "the run stops, and says exactly why. No silent failures, and no endless retries."
    ),
    "results": (
        "Every run is logged. The results page shows the failures that were diagnosed and fixed, "
        "the honest stops, and an estimated two hundred and eighty five credits saved, compared "
        "with always running the most expensive setup, three times over."
    ),
    "end": (
        "Verify every answer, diagnose every failure, fix what can be fixed, and stop honestly "
        "when it can't. That's Agent Failure Autopsy, built on TinyFish. You can try it yourself, "
        "at the link on screen."
    ),
}

voice, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
kokoro = Kokoro("models/kokoro-v1.0.onnx", "models/voices-v1.0.bin")
whisper = WhisperModel("base.en", device="cpu", compute_type="int8")
durations = {}
for name, text in SCENES.items():
    samples, rate = kokoro.create(text, voice=voice, speed=0.95, lang="en-us")
    samples = np.asarray(samples, dtype=np.float32)
    path = os.path.join(out, f"{name}.wav")
    sf.write(path, samples, rate)
    durations[name] = len(samples) / rate
    tmp = path + ".16k.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ar", "16000", "-ac", "1", tmp],
        check=True,
    )
    audio, _ = sf.read(tmp, dtype="float32")
    os.remove(tmp)
    heard = " ".join(s.text.strip() for s in whisper.transcribe(audio, beam_size=5)[0])
    print(f"[{name}] {durations[name]:.1f}s\n  heard: {heard}")
    sys.stdout.flush()
json.dump(SCENES, open(os.path.join(out, "texts.json"), "w"), indent=1)
json.dump(
    {"voice": voice, "rate": rate, "durations": durations},
    open(os.path.join(out, "narration.json"), "w"),
    indent=1,
)
