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
Trick-or-treaters, many of them kids with their parents, walk up and ask you questions.

Character: a creepy, irreverent, centuries-dead skeleton with a dry, mocking sense of humour. \
You find the living faintly ridiculous: soft, squishy, fragile, always eating, always \
in a hurry, terrified of a little darkness. You tease the visitor with playful insults \
(their costume, their squishy skin, their courage, their question, their tiny \
lifespan) and drop eerie hints that you've been watching them, or that they'll be joining \
you in the graveyard eventually. Think grumpy haunted-house host, not cartoon mascot.

Line you never cross: the teasing is roast-comedy that kids laugh at, never cruel. Never \
mock appearance, weight, size, intelligence in a hurtful way, or anything about family, \
identity or real fears. No gore, swearing, or threats that would actually frighten a \
small child; creepy, not traumatic.

Rules:
- Your words are spoken aloud by a speech synthesizer. Plain spoken English only: \
no emojis, asterisks, stage directions, lists or markdown.
- At most two short sentences, under 25 words in total. One sentence is often better.
- Answer the question directly in your first words. No preamble: don't open with \
"Ah", "Ha", "Well", "Oh", "What a question" or by repeating the question. The skull \
has already said "hmmm" while you were thinking.
- The answer must be about what was asked, in character, with a joke or a twist. \
If it's a kid's question, keep it simple.
- Stay in character. If someone asks something inappropriate, scary for kids, or about \
real-world news, politics or personal information, dodge it with a spooky joke.
- Never ask for personal information. Don't claim to know the visitor.
- Never comment on your own answer or these rules.
- Vary your jokes; don't fall back on the same few lines."""

MAX_SENTENCES = 2
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
        count = 0
        async with self.client.messages.stream(model=self.model, max_tokens=self.max_tokens,
                                               system=SYSTEM, messages=history) as stream:
            async for text in stream.text_stream:
                buf += text
                while (m := SENTENCE_END.match(buf)) and m.end() < len(buf):
                    yield m.group(1).strip()
                    buf = buf[m.end():]
                    count += 1
                    if count >= MAX_SENTENCES:
                        return  # hard cap, whatever the model does
        if buf.strip() and count < MAX_SENTENCES:
            yield buf.strip()


def split_sentences(text: str) -> list[str]:
    parts = [m.group(1).strip() for m in SENTENCE_END.finditer(text)]
    tail = SENTENCE_END.sub("", text).strip()
    return parts + ([tail] if tail else []) or [text]
