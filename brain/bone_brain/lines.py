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
    "unpossessed": ["Ugh. Sorry about that. Something was borrowing my skull."],
}
PERSONA_KINDS = ("greet", "intro", "reply", "thinking", "goodbye", "silence", "unheard")


class Lines:
    def __init__(self):
        self.pools: dict[str, list[str]] = {}
        self.recent: dict[str, deque] = {}
        for kind, default in FALLBACK.items():
            p = DIR / f"{kind}.txt"
            lines = [l.strip() for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
            self.pools[kind] = lines or default
            self.recent[kind] = deque(maxlen=max(0, min(len(self.pools[kind]) // 2, 50)))
        # Possession personas: lines/personas/<id>/<kind>.txt
        for d in sorted((DIR / "personas").glob("*/")):
            for kind in PERSONA_KINDS:
                f = d / f"{kind}.txt"
                lines = [l.strip() for l in f.read_text().splitlines() if l.strip()] if f.exists() else []
                if lines:
                    key = f"{d.name}/{kind}"
                    self.pools[key] = lines
                    self.recent[key] = deque(maxlen=max(0, min(len(lines) // 2, 50)))

    def adopt(self, persona: str, into: str = "skeleton"):
        """Make `persona`'s lines the skull's own (party mode: --persona wizard)."""
        for kind in PERSONA_KINDS:
            if f"{persona}/{kind}" in self.pools:
                self.pools[f"{into}/{kind}"] = self.pools[f"{persona}/{kind}"]
                self.recent[f"{into}/{kind}"] = self.recent[f"{persona}/{kind}"]

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.pools.items() if "/" not in k}

    def has(self, kind: str, persona: str) -> bool:
        return f"{persona}/{kind}" in self.pools

    def pick(self, kind: str, persona: str | None = None) -> str:
        """A line of this kind, in the persona's own words if it has them."""
        if persona and f"{persona}/{kind}" in self.pools:
            kind = f"{persona}/{kind}"
        pool = self.pools[kind]
        choices = [l for l in pool if l not in self.recent[kind]] or pool
        line = random.choice(choices)
        self.recent[kind].append(line)
        return line
