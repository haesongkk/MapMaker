"""Local upload/generate/preview server. Model environments stay isolated."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse, json, mimetypes, re, shutil, threading
from urllib.parse import unquote, urlsplit
from .scene_run import ROOT, read
from .scene_pipeline import Pipeline, create_run

PIPELINE = Pipeline()
BUSY = threading.Lock()


def background(run):
    try:
        PIPELINE.run(run)
    except Exception:
        pass  # Recorded in the run's status, metadata, and logs.
    finally:
        BUSY.release()


class Handler(BaseHTTPRequestHandler):
    def json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/runs":
            return self.json({"error": "Not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.json({"error": "Invalid upload size"}, 400)
        if not 0 < length <= 25 * 1024 * 1024:
            return self.json({"error": "Upload one image, up to 25 MB"}, 413)
        if not BUSY.acquire(blocking=False):
            return self.json({"error": "A scene is already generating"}, 409)
        try:
            run = create_run(self.rfile.read(length))
        except Exception as exc:
            BUSY.release()
            return self.json({"error": str(exc)}, 400)
        threading.Thread(target=background, args=(run,), daemon=True).start()
        return self.json({"run_id": run.name}, 202)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        match = re.fullmatch(r"/api/runs/([a-f0-9]{32})", path)
        if match:
            run = ROOT / "runs" / match[1]
            if not (run / "status.json").is_file():
                return self.json({"error": "Run not found"}, 404)
            return self.json(
                {
                    "run_id": run.name,
                    **read(run / "status.json"),
                    "metadata": read(run / "scene_metadata.json"),
                }
            )
        if path.startswith("/runs/"):
            match = re.fullmatch(r"/runs/([a-f0-9]{32})/(.+)", path)
            if not match:
                return self.json({"error": "Not found"}, 404)
            base = (ROOT / "runs" / match[1]).resolve()
            file = (base / match[2]).resolve()
        elif path.startswith("/vendor/"):
            base = (ROOT / "web/node_modules").resolve()
            file = (base / path.removeprefix("/vendor/")).resolve()
        else:
            base = (ROOT / "web").resolve()
            file = (
                base / ("index.html" if path == "/" else path.lstrip("/"))
            ).resolve()
        if not file.is_relative_to(base) or not file.is_file():
            return self.json({"error": "Not found"}, 404)
        mime = mimetypes.guess_type(file)[0] or "application/octet-stream"
        if file.suffix == ".js":
            mime = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(file.stat().st_size))
        self.send_header("X-Content-Type-Options", "nosniff")
        if file.name == "scene.glb" and urlsplit(self.path).query == "download":
            self.send_header("Content-Disposition", 'attachment; filename="scene.glb"')
        self.end_headers()
        try:
            with file.open("rb") as f:
                shutil.copyfileobj(f, self.wfile, 1024 * 1024)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8082)
    a = p.parse_args()
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"SAM3D Scene Studio: http://{a.host}:{a.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        PIPELINE.close()


if __name__ == "__main__":
    main()
