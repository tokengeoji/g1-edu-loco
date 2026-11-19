"""Dependency-free browser UI for live read-only telemetry and saved sessions."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from g1stairs.session import read_json

from .telemetry import serialize


class Recording:
    def __init__(self, path):
        self.metadata = read_json(path / "manifest.json")
        self.sample_file = path / "samples.jsonl"
        self.offsets = []
        with self.sample_file.open("rb") as stream:
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line:
                    break
                if line.strip():
                    self.offsets.append(offset)
        if not self.offsets:
            raise ValueError("This completed session has no state samples")

    def sample(self, index):
        if not 0 <= index < len(self.offsets):
            raise ValueError("Sample index out of range")
        with self.sample_file.open("rb") as stream:
            stream.seek(self.offsets[index])
            sample = json.loads(stream.readline())
        return {
            "source": self.metadata["source"],
            "status": "recorded",
            "sample_count": len(self.offsets),
            "sample_index": index,
            "sample": sample,
        }


class Live:
    def __init__(self, receiver, profile, stale_after):
        self.receiver = receiver
        self.profile = profile
        self.stale_after = stale_after

    def sample(self, index):
        current, _ = self.receiver.snapshot()
        if current is None:
            return {"source": "unitree", "status": "waiting", "sample": None}
        received_ns, message = current
        age = (time.monotonic_ns() - received_ns) / 1_000_000_000
        return {
            "source": "unitree",
            "status": "stale" if age > self.stale_after else "live",
            "age_s": age,
            "sample": serialize(message, received_ns, self.profile),
        }


def serve(source, host, port):
    html = Path(__file__).with_name("dashboard.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status, payload):
            self.respond(status, "application/json", json.dumps(payload, allow_nan=False).encode())

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/":
                self.respond(200, "text/html; charset=utf-8", html)
            elif url.path == "/api/sample":
                try:
                    index = int(parse_qs(url.query).get("index", ["0"])[0])
                    payload = source.sample(index)
                except ValueError as exc:
                    self.send_json(400, {"error": str(exc)})
                except OSError as exc:
                    self.send_json(500, {"error": str(exc)})
                else:
                    self.send_json(200, payload)
            else:
                self.send_error(404)

        def log_message(self, format, *args):
            pass

    with ThreadingHTTPServer((host, port), Handler) as server:
        print("Monitoring dashboard at http://{}:{}/".format(host, port), flush=True)
        server.serve_forever()
