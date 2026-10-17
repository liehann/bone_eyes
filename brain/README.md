# brain — the skull's voice (runs on the laptop)

Listens, asks Claude, answers in a skeleton voice, and drives the skull's jaw
and mood over USB serial or UDP. The ESP32 does eyes, jaw servo and radar; this
does everything with audio.

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# models (gitignored, ~550 MB):
mkdir -p models && cd models
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
curl -LO https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
../.venv/bin/python -m piper.download_voices --data-dir . en_GB-alan-medium en_US-ryan-high
cd ..

.venv/bin/python -m bone_brain --out DELL               # real Claude replies
.venv/bin/python -m bone_brain --canned --out DELL      # test mode: canned replies, no API cost
.venv/bin/python -m bone_brain --skull /dev/cu.usbserial-110   # drive the real skull
```

Opens the control page at http://localhost:8031: trigger a visit (mic or
typed questions), test the voice, switch speaker / TTS engine / voice / pitch,
watch the transcript, jaw meter and per-turn timings.

## Pipeline

mic (16 kHz) → Silero VAD (end of question after 0.6 s quiet) → Whisper
small.en on the GPU (mlx-whisper) → Claude Haiku, streamed → each sentence to
TTS as soon as it's complete → voice effects (pitch down, chorus, reverb) →
speaker. The jaw follows the loudness of the dry voice, timed to when the
audio reaches the speaker, minus a small lead for the servo.

- **Keys:** `ANTHROPIC_API_KEY` (and optional `ELEVENLABS_API_KEY`) from the
  environment, else the `bone_eyes` Infisical project (`--env prod`). Memory only.
- **TTS backends** (`--tts`): `kokoro` (default, best local voice), `piper`
  (fastest), `say` (macOS voices), `elevenlabs` (needs a voice id).
- **Lines** (`bone_brain/lines/*.txt`, one per line): greetings, goodbyes,
  silence / unheard prompts, thinking fillers, and 500 fake replies for
  `--canned` mode. Greetings and goodbyes are used in both modes.
- **No recordings** of visitors are kept.
- If Claude fails or there's no internet, the skull says an "offline" line.

## Skull link protocol

Lines starting with `!` share the ESP32's serial console:

| Direction | Message | Meaning |
|---|---|---|
| laptop → skull | `!j <0-1000>` | jaw opening |
| | `!m idle\|alert\|talking\|goodbye` | mood |
| | `!l <x> <y>` / `!l` | look at (-1..1) / release gaze |
| skull → laptop | `!p <cm>` | someone present at this distance |
| | `!g` | they left |
