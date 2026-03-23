from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


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


def generate_answer(question: str) -> str:
    text = question.lower()
    keyword_pairs = [
        (
            ("accounting",),
            "Her background is in accounting, and she is also exploring new links between business, data, and creativity.",
        ),
        (
            ("ai", "sora", "stable diffusion", "comfyui"),
            "She has built solid hands-on experience in AI animation and AI application workflows, and she is open to discussing those tools further.",
        ),
        (
            ("school", "business school", "graduate", "graduated"),
            "She graduated from Shanghai Business School, and that experience helped shape both her business perspective and open way of thinking.",
        ),
        (
            ("english", "speaking"),
            "She has strong spoken English skills and can communicate confidently with international teams.",
        ),
        (
            ("career", "job", "future"),
            "She sees career growth as the natural result of continuous learning, practice, and long-term development.",
        ),
    ]

    for keywords, answer in keyword_pairs:
        if any(keyword in text for keyword in keywords):
            return answer

    return "Thanks for your message. It has been saved, and visitors can now see this public Q and A on the board."


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

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
                "answer": generate_answer(question),
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
    ensure_store()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), AppHandler)
    print("Serving on http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
