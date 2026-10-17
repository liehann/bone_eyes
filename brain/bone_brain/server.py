"""Local control page (http://localhost:8031): live state, transcript, timings,
jaw meter, voice/persona editor, and buttons to drive the brain without a
visitor or radar."""
import asyncio
import json
import weakref
from pathlib import Path

from aiohttp import WSMsgType, web

from .audio import default_name, output_devices
from .convo import Brain
from .personas import PERSONAS

STATIC = Path(__file__).resolve().parent / "static"


class Server:
    def __init__(self):
        self.clients: weakref.WeakSet = weakref.WeakSet()
        self.brain: Brain | None = None
        self._voices: dict[str, list[str]] = {}

    def emit(self, msg: dict):
        data = json.dumps(msg)
        for ws in list(self.clients):
            if not ws.closed:
                asyncio.ensure_future(ws.send_str(data))

    def voices(self) -> dict[str, list[str]]:
        if not self._voices:
            for name, backend in self.brain.tts.backends.items():
                try:
                    self._voices[name] = backend.voices()
                except Exception:
                    self._voices[name] = []
        return self._voices

    def settings(self) -> dict:
        b, c = self.brain, self.brain.cfg
        return {
            "type": "settings", "state": b.state,
            "llm": b.llm_backend, "llm_options": ["claude", "canned"] if b.llm.available else ["canned"],
            "model": c.llm_model,
            "out": c.out_device or default_name("output"), "out_options": output_devices(),
            "skull": b.skull.status, "lines": b.lines.counts(),
            "persona": b.persona.id, "possess_chance": round(b.possession.chance(), 2),
            "personas": {k: v.to_json() for k, v in PERSONAS.items()},
            "engines": self.voices(),
        }

    def set(self, key: str, value):
        b, c = self.brain, self.brain.cfg
        if key == "llm" and value in ("claude", "canned"):
            b.llm_backend = value if (value == "canned" or b.llm.available) else "canned"
        elif key == "out" and value in output_devices():
            b.player.set_device(value)
        elif key == "possess":
            b.possession.force(value)

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
            try:
                if cmd == "visitor":
                    b.visitor()
                elif cmd == "ask" and m.get("text"):
                    b.visitor([t for t in m["text"].split("\n") if t.strip()])
                elif cmd == "leave":
                    b.leave()
                elif cmd == "stop":
                    b.stop()
                elif cmd == "set":
                    self.set(m.get("key"), m.get("value"))
                    self.emit(self.settings())
                elif cmd == "persona_set":
                    persona = PERSONAS[m["id"]]
                    persona.update(m["key"], m["value"])
                    voices = self.voices().get(persona.engine, [])
                    if m["key"] == "engine" and voices and persona.voice not in voices:
                        persona.voice = voices[0]  # keep the voice valid for the new engine
                    asyncio.ensure_future(b._refill_fillers(m["id"]))  # re-render its "hmmm"s
                    self.emit({"type": "persona_data", "id": m["id"], "data": PERSONAS[m["id"]].to_json(),
                               "dirty": True})
                elif cmd == "persona_save":
                    PERSONAS[m["id"]].save()
                    self.emit({"type": "persona_data", "id": m["id"], "data": PERSONAS[m["id"]].to_json(),
                               "dirty": False, "saved": True})
                elif cmd == "preview" and m.get("text") and not b.busy():
                    b.session = asyncio.ensure_future(b.preview(m["id"], m["text"]))
            except Exception as e:
                await ws.send_str(json.dumps({"type": "line", "who": "error", "text": f"{cmd}: {e}"}))
        return ws

    async def index(self, request):
        return web.FileResponse(STATIC / "index.html")

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/ws", self.ws)
        return app
