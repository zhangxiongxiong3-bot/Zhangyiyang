from __future__ import annotations

import gzip
import io
import json
import mimetypes
import traceback
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# Cache durations in seconds
_CACHE_LONG = 31536000   # 1 year — images, videos, fonts
_CACHE_SHORT = 3600      # 1 hour — HTML
_COMPRESSIBLE = {
    "text/html", "text/css", "text/javascript", "application/javascript",
    "application/json", "image/svg+xml",
}


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MESSAGES_FILE = DATA_DIR / "messages.json"


def ensure_store() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not MESSAGES_FILE.exists():
        MESSAGES_FILE.write_text("[]", encoding="utf-8")


def load_messages() -> list[dict]:
    ensure_store()
    try:
        raw = MESSAGES_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            MESSAGES_FILE.write_text("[]", encoding="utf-8")
            return []
        data = json.loads(raw)
        if not isinstance(data, list):
            MESSAGES_FILE.write_text("[]", encoding="utf-8")
            return []
        return data
    except json.JSONDecodeError:
        MESSAGES_FILE.write_text("[]", encoding="utf-8")
        return []


def save_messages(messages: list[dict]) -> None:
    ensure_store()
    MESSAGES_FILE.write_text(
        json.dumps(messages, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def _cache_header(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self.send_header("Cache-Control", f"public, max-age={_CACHE_SHORT}")
        else:
            self.send_header("Cache-Control", f"public, max-age={_CACHE_LONG}, immutable")

    def send_head(self):
        path = urlparse(self.path).path
        # Only handle static files here; API routes go through do_GET
        if path.startswith("/api/"):
            return None
        file = self.translate_path(self.path)
        f = None
        try:
            f = open(file, "rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return None

        mime = mimetypes.guess_type(file)[0] or "application/octet-stream"
        raw = f.read()
        f.close()

        # Gzip compress compressible types if client supports it
        accept_enc = self.headers.get("Accept-Encoding", "")
        use_gzip = "gzip" in accept_enc and mime in _COMPRESSIBLE
        if use_gzip:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
                gz.write(raw)
            body = buf.getvalue()
        else:
            body = raw

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self._cache_header()
        self.end_headers()
        return io.BytesIO(body)

    def _send_json(self, payload: dict | list, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/messages":
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/messages":
            messages = load_messages()
            print(f"[GET] /api/messages -> {len(messages)} messages")
            self._send_json(messages)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/messages":
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            print(f"[POST] /api/messages raw body: {raw_body!r}")
            body = json.loads(raw_body.decode("utf-8"))
            print(f"[POST] /api/messages parsed body: {body}")
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            print("[POST] JSON parse failed:")
            traceback.print_exc()
            self._send_json(
                {"error": f"Invalid JSON payload: {error}"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            print("[POST] Unexpected request read failure:")
            traceback.print_exc()
            self._send_json(
                {"error": f"Request read failure: {error}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        question = str(body.get("question", "")).strip()
        if not question:
            self._send_json({"error": "Question is required"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            messages = load_messages()
            entry = {
                "id": len(messages) + 1,
                "question": question,
                "answer": "",
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            messages.insert(0, entry)
            save_messages(messages)
            print(f"[POST] saved message #{entry['id']} to {MESSAGES_FILE}")
            self._send_json(
                {"success": True, "entry": entry, "count": len(messages)},
                HTTPStatus.CREATED,
            )
        except Exception as error:
            print("[POST] Save failure:")
            traceback.print_exc()
            self._send_json(
                {"error": f"Save failure: {error}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )


def main() -> None:
    import os
    ensure_store()
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print(f"Serving on http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
