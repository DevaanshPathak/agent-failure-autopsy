# Demo video

Records the live site in Chrome, narrates it with a local neural voice, and edits the two together.
The rendered videos go to `demo-video/` at the repo root (gitignored).

- **Recording** (`record.mjs`): Playwright drives the system Chrome against https://agent-failure-autopsy.vercel.app and saves every screencast frame with its timestamp, plus scene marks. It clicks three prepared autopsies, so it starts **real live runs**: about 10 TinyFish credits and a cent of Claude.
- **Voice** (`narration.py`): [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) runs locally (Apache-2.0, no API key), one line per scene. Default voice `hm_omega` (Indian English male); `hm_psi` is the other one. Each line is transcribed back with Whisper to catch mispronunciations.
- **Edit** (`build.py`): fits each scene to its narration (sped up or slowed down within 0.8–3×), adds the title and end cards from `cards.mjs`, normalises loudness to −16 LUFS, and writes captions (`.srt`) plus a copy with them burned in. Needs `ffmpeg` on PATH.

## Make it

Use a working directory outside the repo (frames and models are large):

```sh
W=/path/to/work && mkdir -p $W/models && cp scripts/demo-video/* $W/ && cd $W
uv venv --python 3.12 tts && VIRTUAL_ENV=$W/tts uv pip install kokoro-onnx soundfile faster-whisper
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  curl -L -o models/$f https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f
done
npm init -y && npm i playwright-core

node record.mjs take1                       # ~3 min, live runs
tts/Scripts/python narration.py hm_omega narr   # tts/bin/python on macOS/Linux
node cards.mjs .
tts/Scripts/python build.py take1 narr . out
```

The narration quotes this take's numbers (credits per run, credits saved on the results page): update `SCENES` in `narration.py` if a new take differs.
