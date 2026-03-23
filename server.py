from __future__ import annotations

import json
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
        return json.loads(MESSAGES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
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
        (("accounting", "会计"), "她的专业基础是会计，同时也在持续探索商业、数据与创意结合的更多可能。"),
        (("ai", "人工智能", "sora", "stable diffusion", "comfyui"), "她在 AI 动画与 AI 应用开发方面投入了不少实践，也愿意继续交流相关工具和创作经验。"),
        (("school", "上海商学院", "business school", "毕业"), "她毕业于上海商学院，这段学习经历也塑造了她兼具商业视角与开放思维的成长方式。"),
        (("english", "英语", "口语"), "她具备较强的英语口语表达能力，能够比较自信地和国际团队沟通。"),
        (("career", "工作", "就业", "future", "未来"), "她相信就业是持续成长后的自然结果，也会把学习、实践与表达能力一起带进未来的发展路径里。"),
    ]

    for keywords, answer in keyword_pairs:
        if any(keyword in text for keyword in keywords):
            return answer

    return "谢谢你的留言。这个问题已经被记录下来，访客现在也能在公开留言板里看到这条问答。"


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _send_json(self, payload: dict | list, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/messages":
            self._send_json(load_messages())
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/messages":
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "Invalid JSON payload"}, HTTPStatus.BAD_REQUEST)
            return

        question = str(body.get("question", "")).strip()
        if not question:
            self._send_json({"error": "Question is required"}, HTTPStatus.BAD_REQUEST)
            return

        messages = load_messages()
        entry = {
            "id": len(messages) + 1,
            "question": question,
            "answer": generate_answer(question),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        messages.insert(0, entry)
        save_messages(messages)
        self._send_json(entry, HTTPStatus.CREATED)


def main() -> None:
    ensure_store()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), AppHandler)
    print("Serving on http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
