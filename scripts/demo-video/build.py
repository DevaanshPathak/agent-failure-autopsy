"""Cut the recorded take into scenes, fit each to its narration, add cards, mux the voice.
Usage: python build.py <take-dir> <narration-dir> <cards-dir> <out-dir>"""

import json
import os
import re
import subprocess
import sys

import numpy as np
import soundfile as sf

take, narr, cards, out = (os.path.abspath(p) for p in sys.argv[1:5])
os.makedirs(out, exist_ok=True)
work = os.path.join(out, "work")
os.makedirs(work, exist_ok=True)

FPS = 30
LEAD, TAIL = 0.35, 0.65  # silence before/after each narration line
TITLE_S = 2.6
SCENES = [  # (scene, start mark, end mark)
    ("intro", "intro", "cards"),
    ("cards", "cards", "run1"),
    ("run1", "run1", "run1-done"),
    ("run2", "run2", "run2-done"),
    ("run3", "run3", "run3-done"),
    ("results", "results", "results-done"),
]

frames = sorted(json.load(open(os.path.join(take, "frames.json"))), key=lambda f: f["ts"])
marks = {m["name"]: m["ts"] for m in json.load(open(os.path.join(take, "marks.json")))}
meta = json.load(open(os.path.join(narr, "narration.json")))
durs = meta["durations"]


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def encode_args() -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-r",
        str(FPS),
        "-pix_fmt",
        "yuv420p",
    ]


def scene_clip(name: str, a: float, b: float, target: float) -> str:
    """Frames between marks a..b, sped up or slowed down to last `target` seconds."""
    shown = [f for f in frames if f["ts"] <= a][-1:] + [f for f in frames if a < f["ts"] < b]
    lines = ["ffconcat version 1.0"]
    for i, f in enumerate(shown):
        start = a if i == 0 else f["ts"]
        end = shown[i + 1]["ts"] if i + 1 < len(shown) else b
        path = os.path.join(take, "frames", f["file"]).replace("\\", "/")
        lines += [f"file '{path}'", f"duration {max(end - start, 0.001):.4f}"]
    lines.append(f"file '{os.path.join(take, 'frames', shown[-1]['file']).replace(chr(92), '/')}'")
    listing = os.path.join(work, f"{name}.ffconcat")
    open(listing, "w").write("\n".join(lines) + "\n")
    raw = b - a
    speed = min(3.0, max(0.8, raw / target))
    pad = max(0.0, target - raw / speed) + 0.5
    vf = (
        f"setpts=PTS/{speed:.4f},fps={FPS},scale=1920:1080:flags=lanczos,"
        f"tpad=stop_mode=clone:stop_duration={pad:.3f},trim=duration={target:.3f},setpts=PTS-STARTPTS"
    )
    clip = os.path.join(work, f"{name}.mp4")
    ffmpeg("-f", "concat", "-safe", "0", "-i", listing, "-vf", vf, *encode_args(), "-an", clip)
    print(f"{name:8} recorded {raw:5.1f}s -> {target:5.1f}s (x{speed:.2f})")
    return clip


def still_clip(name: str, png: str, seconds: float, fade_in: bool, fade_out: bool) -> str:
    fades = []
    if fade_in:
        fades.append("fade=t=in:st=0:d=0.6")
    if fade_out:
        fades.append(f"fade=t=out:st={seconds - 0.9:.2f}:d=0.9")
    vf = ",".join([f"fps={FPS}", "scale=1920:1080", *fades]) or "null"
    clip = os.path.join(work, f"{name}.mp4")
    ffmpeg("-loop", "1", "-t", f"{seconds:.3f}", "-i", png, "-vf", vf, *encode_args(), "-an", clip)
    print(f"{name:8} still {seconds:.1f}s")
    return clip


# --- Video ---------------------------------------------------------------------------------------
timeline: list[tuple[str, float, str | None]] = []  # (clip, seconds, narration scene)
timeline.append(
    (
        still_clip("title", os.path.join(cards, "card_title.png"), TITLE_S, True, False),
        TITLE_S,
        None,
    )
)
for name, a, b in SCENES:
    target = LEAD + durs[name] + TAIL
    timeline.append((scene_clip(name, marks[a], marks[b], target), target, name))
end_s = LEAD + durs["end"] + 1.6
timeline.append(
    (still_clip("end", os.path.join(cards, "card_end.png"), end_s, False, True), end_s, "end")
)

concat = os.path.join(work, "all.txt")
open(concat, "w").write("".join(f"file '{c.replace(chr(92), '/')}'\n" for c, _, _ in timeline))
video = os.path.join(work, "video.mp4")
ffmpeg("-f", "concat", "-safe", "0", "-i", concat, "-c", "copy", video)

# --- Narration track and captions ----------------------------------------------------------------
rate = meta["rate"]
total = sum(s for _, s, _ in timeline)
track = np.zeros(int((total + 1) * rate), dtype=np.float32)
captions = []
t = 0.0
texts = json.load(open(os.path.join(narr, "texts.json")))
for _, seconds, scene in timeline:
    if scene:
        voice, _ = sf.read(os.path.join(narr, f"{scene}.wav"), dtype="float32")
        start = t + LEAD
        i = int(start * rate)
        track[i : i + len(voice)] += voice
        # Captions: sentences (long ones split at commas), timed by their share of the characters.
        parts = []
        for sentence in re.split(r"(?<=[.!?:])\s+", texts[scene]):
            if len(sentence) > 84:
                parts += [p.strip() for p in re.split(r"(?<=,)\s+", sentence) if p.strip()]
            else:
                parts.append(sentence)
        chars = sum(len(p) for p in parts)
        cursor = start
        for p in parts:
            length = durs[scene] * len(p) / chars
            captions.append((cursor, cursor + length, p))
            cursor += length
    t += seconds
narration = os.path.join(work, "narration.wav")
sf.write(narration, track, rate)


def stamp(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


srt = os.path.join(out, "agent-failure-autopsy-demo.srt")
with open(srt, "w", encoding="utf-8") as f:
    for n, (a, b, text) in enumerate(captions, 1):
        f.write(f"{n}\n{stamp(a)} --> {stamp(b)}\n{text}\n\n")

final = os.path.join(out, "agent-failure-autopsy-demo.mp4")
ffmpeg(
    "-i",
    video,
    "-i",
    narration,
    "-map",
    "0:v",
    "-map",
    "1:a",
    "-c:v",
    "copy",
    "-af",
    "loudnorm=I=-16:TP=-1.5:LRA=11",
    "-c:a",
    "aac",
    "-b:a",
    "192k",
    "-ar",
    "48000",
    "-ac",
    "2",
    "-movflags",
    "+faststart",
    "-shortest",
    final,
)
print(f"final: {final} ({total:.1f}s)")

# A copy with captions burned in, for viewers watching muted.
style = (
    "FontName=Segoe UI,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,"
    "BackColour=&H80000000,BorderStyle=4,Outline=1,Shadow=0,MarginV=14"
)
captioned = os.path.join(out, "agent-failure-autopsy-demo-captioned.mp4")
subprocess.run(
    [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        os.path.basename(final),
        "-vf",
        f"subtitles={os.path.basename(srt)}:force_style='{style}'",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        os.path.basename(captioned),
    ],
    check=True,
    cwd=out,
)
print(f"captioned: {captioned}")
