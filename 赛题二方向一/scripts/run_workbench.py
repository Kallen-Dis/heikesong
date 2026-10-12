"""Loopback-only server; static root is exclusively demo/workbench."""
from __future__ import annotations
import argparse
import json
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.task_runtime import TaskRuntime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    runtime = TaskRuntime()
    static = ROOT / "demo" / "workbench"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def respond(self, value, status=200):
            payload = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in {"/api/state", "/api/export"}:
                return self.respond(runtime.snapshot())
            name = "index.html" if path == "/" else path.lstrip("/")
            if name not in {"index.html", "workbench.css", "workbench.js"}:
                return self.respond({"error": "not_found"}, 404)
            file = static / name
            if not file.exists(): return self.respond({"error": "static_missing"}, 404)
            data = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", {".html": "text/html", ".css": "text/css", ".js": "application/javascript"}[file.suffix]+"; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            # Prevent cross-origin browser pages from spending model API credits.
            origin = self.headers.get("Origin")
            if origin and origin != f"http://127.0.0.1:{args.port}":
                return self.respond({"error": "origin_rejected"}, 403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 16384: raise ValueError("payload too large")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict): raise ValueError("object required")
                path = urlparse(self.path).path
                if path == "/api/reset": result = runtime.reset(**body)
                elif path == "/api/step": result = runtime.step(**body)
                elif path == "/api/weights": result = runtime.set_weights(**body)
                elif path == "/api/mutate": result = runtime.mutate(**body)
                elif path == "/api/action":
                    runtime.action(body.get("tool"), body.get("arguments"), actor="人类")
                    result = runtime.snapshot()
                else: return self.respond({"error": "not_found"}, 404)
                self.respond(result)
            except (ValueError, TypeError, KeyError) as exc:
                self.respond({"error": str(exc)}, 400)
            except Exception as exc:
                self.respond({"error": type(exc).__name__, "message": "任务执行失败；没有使用伪造回退。"}, 500)

    print(f"Task recovery workbench http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__": main()
