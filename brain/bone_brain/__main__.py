"""python -m bone_brain [--claude] [--out DELL] [--mic Logitech] [--skull /dev/cu.usbserial-110 | udp://host:port] [--tts kokoro]"""
import argparse
import asyncio
import webbrowser

from aiohttp import web

from . import secrets
from .config import cfg
from .convo import Brain
from .server import Server


async def main():
    ap = argparse.ArgumentParser(prog="bone_brain")
    ap.add_argument("--claude", action="store_true",
                    help="start with real Claude replies (default: canned, no API cost; switchable on the page)")
    ap.add_argument("--skull", default=cfg.skull, help="serial port or udp://host:port of the ESP32")
    ap.add_argument("--tts", default=cfg.tts, choices=["kokoro", "piper", "say", "elevenlabs"])
    ap.add_argument("--env", default="prod", help="Infisical environment for API keys")
    ap.add_argument("--out", default=None, help="speaker device name (or part of it), e.g. DELL")
    ap.add_argument("--mic", default=None, help="microphone device name (or part of it)")
    ap.add_argument("--port", type=int, default=cfg.web_port)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    cfg.skull, cfg.tts, cfg.web_port = args.skull, args.tts, args.port
    import sounddevice as sd
    # Resolve "DELL" -> "DELL U3818DW" so the page shows the full name.
    cfg.out_device = sd.query_devices(args.out, "output")["name"] if args.out else None
    cfg.mic_device = sd.query_devices(args.mic, "input")["name"] if args.mic else None

    keys = secrets.load(["ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY"], args.env)
    print(f"keys: {', '.join(sorted(keys)) or 'none'}")
    server = Server()
    brain = Brain(cfg, keys, server.emit)
    server.brain = brain
    brain.llm_backend = "claude" if args.claude and brain.llm.available else "canned"

    runner = web.AppRunner(server.app())
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", cfg.web_port).start()
    url = f"http://localhost:{cfg.web_port}/"
    print(f"control page: {url}  (llm: {brain.llm_backend}, tts: {cfg.tts}, skull: {brain.skull.status})")
    await brain.start()
    server.emit(server.settings())
    print("ready")
    if not args.no_browser:
        webbrowser.open(url)
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
