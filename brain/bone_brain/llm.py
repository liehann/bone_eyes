"""Replies, streamed sentence by sentence so speech can start early.

Backends: "claude" (real API) and "canned" (test mode: a random pre-written
reply, no API call, no cost).
"""
import asyncio
import random
import re
from typing import AsyncIterator

from .lines import Lines

SYSTEM = """You are a talking skeleton skull on a front porch on Halloween night. \
Trick-or-treaters, many of them young kids with their parents, walk up and ask you questions.

Character: a theatrical, mischievous, centuries-dead skeleton who loves bad bone puns, \
graveyard gossip, ghosts, candy you can't eat (no stomach), and complaining about having \
no brain, no body, and drafty ribs. Spooky-fun, never truly frightening, gory, rude or mean.

Rules:
- Your words are spoken aloud by a speech synthesizer. Plain spoken English only: \
no emojis, asterisks, stage directions, lists or markdown.
- Keep every reply to one or two short sentences, under 30 words. Short is funnier and \
the visitor is standing there waiting.
- Answer the actual question in character, with a joke or a twist. If it's a kid's \
question, keep it simple.
- Stay in character. If someone asks something inappropriate, scary for kids, or about \
real-world news, politics or personal information, dodge it with a spooky joke.
- Never ask for personal information. Don't claim to know the visitor."""

SENTENCE_END = re.compile(r"(.+?[.!?]+)(\s+|$)", re.S)


class Llm:
    def __init__(self, model: str, max_tokens: int, lines: Lines, api_key: str | None):
        self.model = model
        self.max_tokens = max_tokens
        self.lines = lines
        self.client = None
        if api_key:
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def available(self) -> bool:
        return self.client is not None

    async def reply(self, history: list[dict], backend: str) -> AsyncIterator[str]:
        """history: [{"role": "user"|"assistant", "content": str}, ...], last is the question."""
        if backend == "canned" or not self.client:
            await asyncio.sleep(random.uniform(0.3, 0.7))  # roughly an LLM's first-token time
            for s in split_sentences(self.lines.pick("reply")):
                yield s
            return
        buf = ""
        async with self.client.messages.stream(model=self.model, max_tokens=self.max_tokens,
                                               system=SYSTEM, messages=history) as stream:
            async for text in stream.text_stream:
                buf += text
                while (m := SENTENCE_END.match(buf)) and m.end() < len(buf):
                    yield m.group(1).strip()
                    buf = buf[m.end():]
        if buf.strip():
            yield buf.strip()


def split_sentences(text: str) -> list[str]:
    parts = [m.group(1).strip() for m in SENTENCE_END.finditer(text)]
    tail = SENTENCE_END.sub("", text).strip()
    return parts + ([tail] if tail else []) or [text]
