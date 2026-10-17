"""Pre-written lines (bone_brain/lines/*.txt): greetings, goodbyes, fillers, and
the fake replies used by the canned LLM. Picks avoid recent repeats."""
import random
from collections import deque
from pathlib import Path

DIR = Path(__file__).resolve().parent / "lines"
FALLBACK = {
    "greet": ["Well, well, a visitor! Come closer and ask me anything, if you dare."],
    "reply": ["The spirits say yes, but they also say they want a snack."],
    "goodbye": ["Farewell, mortal. Don't let the bats bite."],
    "silence": ["Too scared to speak? I don't blame you."],
    "unheard": ["Speak up, my ears fell off a few centuries ago."],
    "thinking": ["Hmmm, let me consult the spirits."],
    "offline": ["The spirits are silent tonight. Ask me again later."],
}


class Lines:
    def __init__(self):
        self.pools: dict[str, list[str]] = {}
        self.recent: dict[str, deque] = {}
        for kind, default in FALLBACK.items():
            p = DIR / f"{kind}.txt"
            lines = [l.strip() for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
            self.pools[kind] = lines or default
            self.recent[kind] = deque(maxlen=max(0, min(len(self.pools[kind]) // 2, 50)))

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.pools.items()}

    def pick(self, kind: str) -> str:
        pool = self.pools[kind]
        choices = [l for l in pool if l not in self.recent[kind]] or pool
        line = random.choice(choices)
        self.recent[kind].append(line)
        return line
