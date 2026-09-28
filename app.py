from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from recommender import CourseRecommender
from agent import RecommendationAgent


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
PROFILE_FILE = ROOT / "student_profile.json"


class Handler(SimpleHTTPRequestHandler):
    engine = CourseRecommender(ROOT)
    agent = RecommendationAgent(engine)

    def _json(self, value, status=HTTPStatus.OK):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/stats":
            return self._json(self.engine.stats())
        if path == "/api/profile":
            value = json.loads(PROFILE_FILE.read_text()) if PROFILE_FILE.exists() else {}
            return self._json(value)
        requested = "index.html" if path == "/" else path.lstrip("/")
        target = (WEB / requested).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            value = self._body()
            if self.path == "/api/profile":
                PROFILE_FILE.write_text(json.dumps(value, indent=2), encoding="utf-8")
                return self._json({"saved": True, "profile": value})
            if self.path == "/api/recommend":
                profile = value.get("profile") or (json.loads(PROFILE_FILE.read_text()) if PROFILE_FILE.exists() else {})
                return self._json(self.agent.run(profile, str(value.get("query", "")), int(value.get("limit", 8))))
            return self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description="Run the BITS Academic Course Recommender dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Dashboard: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
