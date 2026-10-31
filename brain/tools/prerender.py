"""Render every line of a persona through ElevenLabs into the on-disk cache
(brain/cache/tts/), so the brain plays them with no network or API call.

    brain/.venv/bin/python brain/tools/prerender.py wizard [--dry-run] [--env prod]

One API call per distinct sentence; sentences already cached are skipped, so
re-running only fills gaps. The brain splits lines into sentences before
speaking, so the cache is keyed per sentence (voice + model + text).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bone_brain import secrets  # noqa: E402
from bone_brain.config import cfg  # noqa: E402
from bone_brain.lines import DIR, PERSONA_KINDS  # noqa: E402
from bone_brain.llm import split_sentences  # noqa: E402
from bone_brain.personas import PERSONAS  # noqa: E402
from bone_brain.tts import ElevenLabs, cache_file  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("persona")
    ap.add_argument("--dry-run", action="store_true", help="count what would be rendered, call nothing")
    ap.add_argument("--env", default="prod")
    args = ap.parse_args()
    p = PERSONAS[args.persona]
    if p.engine != "elevenlabs":
        sys.exit(f"{p.id} uses {p.engine}, not elevenlabs")
    sentences: dict[str, str] = {}   # sentence -> kind (first seen)
    for kind in PERSONA_KINDS:
        f = DIR / "personas" / p.id / f"{kind}.txt"
        for line in (f.read_text().splitlines() if f.exists() else []):
            for s in split_sentences(line.strip()) if line.strip() else []:
                sentences.setdefault(s, kind)
    todo = [s for s in sentences if not cache_file(p.voice, p.model, s).exists()]
    print(f"{p.id}: {len(sentences)} sentences, {len(sentences) - len(todo)} cached, {len(todo)} to render")
    if args.dry_run or not todo:
        return
    key = secrets.load(["ELEVENLABS_API_KEY"], args.env).get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY not found (env or bone_eyes Infisical project); nothing rendered")
    b = ElevenLabs(cfg, key)
    for i, s in enumerate(todo, 1):
        b.synth(s, p.voice, p.speed, p.model)   # writes the cache file
        print(f"[{i}/{len(todo)}] {sentences[s]:>8}: {s}", flush=True)


if __name__ == "__main__":
    main()
