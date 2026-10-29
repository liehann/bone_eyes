"""Link to the ESP32 (the skull's body): jaw, mood and gaze out; presence in.

Transport: USB serial (cfg.skull = "/dev/cu.usbserial-...") or UDP
("udp://bone-eyes.local:4210"). Machine messages are single lines starting with
"!" so they share the serial console with human commands:
  laptop -> skull:  !j <0-1000>     jaw opening
                    !m <idle|alert|talking|goodbye>
                    !l <x> <y>       gaze, -1..1 (+x skull's right, +y up); "!l" alone releases
                    !a <fire|default|dragon>   eye style (follows the speaking persona);
                                     a temporary override of the skull's saved style
                    !a               drop the override: back to the saved style
  skull -> laptop:  !p <cm>          someone is present at this distance
                    !g               they're gone
"""
import socket
import threading
import time

MOODS = ("idle", "alert", "talking", "goodbye")


class Skull:
    def __init__(self, target: str, on_event=None):
        self.target = target
        self.on_event = on_event or (lambda kind, value: None)
        self.ser = None
        self.sock = None
        self.addr = None
        self.lock = threading.Lock()
        self.last_jaw = 0.0
        self.status = "not connected (simulated)"
        if not target:
            return
        try:
            if target.startswith("udp://"):
                host, port = target[6:].rsplit(":", 1)
                self.addr = (socket.gethostbyname(host), int(port))
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.bind(("", int(port)))
                self.sock.settimeout(0.5)
                self.status = f"udp {self.addr[0]}:{self.addr[1]}"
            else:
                import serial
                self.ser = serial.Serial(target, 115200, timeout=0.5)
                self.status = f"serial {target}"
            threading.Thread(target=self._reader, daemon=True).start()
        except Exception as e:
            self.status = f"error: {e}"

    @property
    def connected(self) -> bool:
        return bool(self.ser or self.sock)

    def _send(self, line: str):
        data = (line + "\n").encode()
        with self.lock:
            try:
                if self.ser:
                    self.ser.write(data)
                elif self.sock:
                    self.sock.sendto(data, self.addr)
            except Exception as e:
                self.status = f"error: {e}"

    def jaw(self, level: float):
        self.last_jaw = level
        self._send(f"!j {int(max(0.0, min(1.0, level)) * 1000)}")

    def mood(self, mood: str):
        if mood in MOODS:
            self._send(f"!m {mood}")

    def art(self, style: str | None = None):
        """Override the eye style; None restores the skull's own (saved) style."""
        if style is None:
            self._send("!a")
        elif style in ("fire", "default", "dragon"):
            self._send(f"!a {style}")

    def look(self, x: float | None = None, y: float = 0.0):
        self._send("!l" if x is None else f"!l {x:.2f} {y:.2f}")

    def _reader(self):
        while True:
            try:
                if self.ser:
                    raw = self.ser.readline()
                else:
                    raw = self.sock.recvfrom(256)[0]
            except socket.timeout:
                continue
            except Exception:
                time.sleep(1)
                continue
            line = raw.decode(errors="replace").strip()
            if line.startswith("!p"):
                parts = line.split()
                self.on_event("present", int(parts[1]) if len(parts) > 1 else 0)
            elif line.startswith("!g"):
                self.on_event("gone", 0)
