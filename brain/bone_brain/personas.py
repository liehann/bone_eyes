"""Possession: now and then another spirit seizes the skull for a reply or three,
with its own voice and character, then the skeleton takes back over.

Timing is deliberately irregular. After a possession ends there's a short
quiet gap; then the chance of another rises with every reply (a rising hazard),
capped so it never becomes predictable, plus a small wildcard chance at any
time. The scheduler persists across visits, so it isn't "every Nth visitor".
"""
import json
import random
from dataclasses import asdict, dataclass, fields
from pathlib import Path

SKELETON = "skeleton"
DIR = Path(__file__).resolve().parent.parent / "personas"   # brain/personas/<id>.json

POSSESSED = """You are a spirit who has just possessed a talking skeleton skull on a front \
porch on Halloween night, and you are using its jaw to answer the trick-or-treaters, many \
of them kids with their parents. Earlier replies in this conversation may have been the \
skeleton or other spirits talking.

"""


@dataclass
class Persona:
    """One voice + character. Stored as brain/personas/<id>.json and editable live
    from the control page."""
    id: str
    name: str
    weight: int = 0          # relative chance when a possession happens (skeleton: 0)
    engine: str = "kokoro"   # kokoro | piper | say | elevenlabs
    voice: str = "bm_fable"  # voice name for that engine (ElevenLabs: voice id)
    speed: float = 1.0       # Kokoro / Piper speaking rate
    model: str = ""          # ElevenLabs model id ("" = eleven_flash_v2_5)
    effects: bool = True
    semitones: float = 0.0   # pitch shift
    reverb: float = 0.25
    chorus: float = 0.2
    eyes: str = "fire"       # LCD eye style: fire | default (hazel) | dragon (slit pupil)
    character: str = ""      # the character part of Claude's system prompt

    def system_prompt(self) -> str:
        return self.character if self.id == SKELETON else POSSESSED + self.character

    def voice_key(self) -> tuple:
        return (self.engine, self.voice, self.speed, self.model, self.effects,
                self.semitones, self.reverb, self.chorus)

    def to_json(self) -> dict:
        return asdict(self)

    def update(self, key: str, value):
        """Set one field from the page, coercing to the field's type."""
        if key not in FIELDS or key == "id":
            raise KeyError(key)
        kind = FIELDS[key]
        if kind is bool:
            value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on")
        else:
            value = kind(value)
        setattr(self, key, value)

    def save(self):
        (DIR / f"{self.id}.json").write_text(json.dumps(self.to_json(), indent=2) + "\n")


FIELDS = {f.name: f.type if isinstance(f.type, type) else
          {"int": int, "float": float, "str": str, "bool": bool}[f.type]
          for f in fields(Persona)}


def load() -> dict[str, Persona]:
    out = {}
    for f in sorted(DIR.glob("*.json")):
        data = json.loads(f.read_text())
        data = {k: v for k, v in data.items() if k in FIELDS}
        p = Persona(**data)
        out[p.id] = p
    if SKELETON not in out:
        out[SKELETON] = Persona(SKELETON, "Skeleton")
    return dict(sorted(out.items(), key=lambda kv: (kv[0] != SKELETON, kv[0])))


PERSONAS = load()


def adopt(pid: str) -> None:
    """Party mode: the skull itself speaks as persona `pid` (voice, effects, eyes,
    character) and no other spirit possesses it. In memory only."""
    src = PERSONAS[pid]
    for k in FIELDS:
        if k not in ("id", "name", "weight"):
            setattr(PERSONAS[SKELETON], k, getattr(src, k))
    PERSONAS[SKELETON].name = src.name
    for p in PERSONAS.values():
        p.weight = 0


class Possession:
    def __init__(self, min_gap: int = 2, hazard: float = 0.06, cap: float = 0.35,
                 wildcard: float = 0.03, max_extra: int = 2):
        self.min_gap, self.hazard, self.cap, self.wildcard, self.max_extra = min_gap, hazard, cap, wildcard, max_extra
        self.current = SKELETON
        self.remaining = 0      # further replies the current spirit gets
        self.since = 0          # skeleton replies since the last possession ended
        self.last = None
        self.forced: str | None = None

    def chance(self) -> float:
        return max(self.wildcard, min(self.cap, self.hazard * max(0, self.since - self.min_gap + 1)))

    def force(self, persona_id: str):
        """Possess on the next reply (control page / testing)."""
        if persona_id in PERSONAS:
            self.forced = persona_id

    def before_reply(self) -> tuple[Persona, str | None]:
        """Decide who answers next. Event: "possessed", "released" or None."""
        if self.forced:
            pid, self.forced = self.forced, None
            if pid == SKELETON:
                return self._release() if self.current != SKELETON else (PERSONAS[SKELETON], None)
            return self._possess(pid)
        if self.current != SKELETON:
            if self.remaining > 0:
                self.remaining -= 1
                return PERSONAS[self.current], None
            return self._release()
        self.since += 1
        if random.random() < self.chance():
            choices = [p for p in PERSONAS.values() if p.weight and p.id != self.last]
            pick = random.choices(choices, weights=[p.weight for p in choices])[0]
            return self._possess(pick.id)
        return PERSONAS[SKELETON], None

    def _possess(self, pid: str):
        self.current = self.last = pid
        self.remaining = random.choice([0, 0, 1, 1, 2][: self.max_extra + 3])
        return PERSONAS[pid], "possessed"

    def _release(self):
        self.current, self.remaining, self.since = SKELETON, 0, 0
        return PERSONAS[SKELETON], "released"

    def end_visit(self):
        """A possession doesn't carry over to the next visitor."""
        if self.current != SKELETON:
            self.current, self.remaining, self.since = SKELETON, 0, 0
