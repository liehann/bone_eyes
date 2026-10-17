"""Local control page (http://localhost:8031): live state, transcript, timings,
jaw meter, and buttons to drive the brain without a visitor or radar."""
import asyncio
import json
import weakref
from pathlib import Path

from aiohttp import WSMsgType, web

from .audio import default_name, output_devices
from .convo import Brain

STATIC = Path(__file__).resolve().parent / "static"


class Server:
    def __init__(self):
        self.clients: weakref.WeakSet = weakref.WeakSet()
        self.brain: Brain | None = None

    def emit(self, msg: dict):
        data = json.dumps(msg)
        for ws in list(self.clients):
            if not ws.closed:
                asyncio.ensure_future(ws.send_str(data))

    def settings(self) -> dict:
        b, c = self.brain, self.brain.cfg
        return {
            "type": "settings",
            "llm": b.llm_backend, "llm_options": ["claude", "canned"] if b.llm.available else ["canned"],
            "tts": c.tts, "tts_options": list(b.tts.backends),
            "voice": self.voice(), "voice_options": self.voices(),
            "fx": c.fx, "semitones": c.fx_semitones, "state": b.state,
            "out": c.out_device or default_name("output"), "out_options": output_devices(),
            "skull": b.skull.status, "lines": b.lines.counts(), "model": c.llm_model,
        }

    def voices(self) -> list[str]:
        try:
            return self.brain.tts.backends[self.brain.cfg.tts].voices()
        except Exception:
            return []

    def voice(self) -> str:
        c = self.brain.cfg
        return {"kokoro": c.kokoro_voice, "piper": c.piper_voice, "say": c.say_voice,
                "elevenlabs": c.elevenlabs_voice_id}.get(c.tts, "")

    def set(self, key: str, value):
        b, c = self.brain, self.brain.cfg
        if key == "llm" and value in ("claude", "canned"):
            b.llm_backend = value if (value == "canned" or b.llm.available) else "canned"
        elif key == "tts" and value in b.tts.backends:
            c.tts = value
        elif key == "voice":
            attr = {"kokoro": "kokoro_voice", "piper": "piper_voice", "say": "say_voice",
                    "elevenlabs": "elevenlabs_voice_id"}[c.tts]
            setattr(c, attr, value)
        elif key == "out" and value in output_devices():
            b.player.set_device(value)
        elif key == "fx":
            c.fx = bool(value)
        elif key == "semitones":
            c.fx_semitones = float(value)
            from .fx import Fx
            b.fx = Fx(c.out_rate, c.fx_semitones, c.fx_reverb)

    async def ws(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_str(json.dumps(self.settings()))
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            m = json.loads(msg.data)
            cmd, b = m.get("cmd"), self.brain
            if cmd == "visitor":
                b.visitor()
            elif cmd == "ask" and m.get("text"):
                b.visitor([t for t in m["text"].split("\n") if t.strip()])
            elif cmd == "say" and m.get("text"):
                if not (b.session and not b.session.done()):
                    b.session = asyncio.ensure_future(b.say(m["text"], who="test"))
            elif cmd == "leave":
                b.leave()
            elif cmd == "stop":
                b.stop()
            elif cmd == "set":
                self.set(m.get("key"), m.get("value"))
                self.emit(self.settings())
                asyncio.ensure_future(b._refill_fillers())  # re-render "hmmm"s in the new voice
        return ws

    async def index(self, request):
        return web.FileResponse(STATIC / "index.html")

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/ws", self.ws)
        return app
