#!/usr/bin/env python3
"""하네스 검증용 목 서버 (표준 라이브러리만).

race/loadgen/grader 파이프라인이 40점 전 항목을 집계하는지 확인하기 위한
최소 타겟이다. 실제 앱이 아니며 경기에 쓰지 않는다.

동작
  POST/GET /v1/user     : 이메일 형식이 틀리면 403(WAF 대역), 정상은 200/201
  POST/GET /v1/product  : 200/201
  PUT  /v1/product      : 200 + image_path 반환 → loadgen 이 /images 풀에 추가
  POST /v1/stress       : 201 즉시 (--stress-delay 로 지연 주입 가능)
  GET  /images/<key>    : 업로드된 키면 200, 아니면 404
  그 외 경로            : 404
  User-Agent 없거나 공격 시그니처(hacker 등) 이면 : 403 (WAF BlockedUserAgents 재현)
"""

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
BLOCKED_UA_RE = re.compile(r"hack|attack|malicious|bot|scanner|sqlmap|nikto|nmap", re.I)

_uploaded = set()
_lock = threading.Lock()
STRESS_DELAY = 0.0
GET_SLEEP_PROB = 0.0
GET_SLEEP_SEC = 0.4


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, payload=None):
        body = json.dumps(payload or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def _ua_ok(self):
        ua = self.headers.get("User-Agent")
        if not ua:
            return False
        return not BLOCKED_UA_RE.search(ua)

    def _maybe_get_sleep(self):
        import random
        import time

        if GET_SLEEP_PROB and random.random() < GET_SLEEP_PROB:
            time.sleep(GET_SLEEP_SEC)

    def do_GET(self):
        if not self._ua_ok():
            return self._send(403, {"error": "blocked"})
        u = urlparse(self.path)
        if u.path == "/healthcheck":
            return self._send(200, {"status": "ok"})
        if u.path.startswith("/images/"):
            key = u.path[len("/images/") :]
            with _lock:
                hit = key in _uploaded
            return (
                self._send(200, {"key": key})
                if hit
                else self._send(404, {"error": "not found"})
            )
        q = parse_qs(u.query)
        if u.path == "/v1/user":
            self._maybe_get_sleep()
            email = (q.get("email") or [""])[0]
            if email and not EMAIL_RE.match(email):
                return self._send(403, {"error": "invalid email"})
            return self._send(
                200,
                {
                    "requestid": (q.get("requestid") or [""])[0],
                    "uuid": (q.get("uuid") or [""])[0],
                    "email": email,
                },
            )
        if u.path == "/v1/product":
            self._maybe_get_sleep()
            return self._send(
                200,
                {
                    "requestid": (q.get("requestid") or [""])[0],
                    "uuid": (q.get("uuid") or [""])[0],
                    "id": (q.get("id") or [""])[0],
                    "price": 100,
                },
            )
        return self._send(404, {"error": "unknown path"})

    def do_POST(self):
        if not self._ua_ok():
            return self._send(403, {"error": "blocked"})
        u = urlparse(self.path)
        body = self._read_json()
        if u.path == "/v1/user":
            email = body.get("email", "")
            if not EMAIL_RE.match(email or ""):
                return self._send(403, {"error": "invalid email"})
            return self._send(201, {"requestid": body.get("requestid"), "email": email})
        if u.path == "/v1/product":
            return self._send(
                201, {"requestid": body.get("requestid"), "id": body.get("id")}
            )
        if u.path == "/v1/stress":
            if STRESS_DELAY:
                import time

                time.sleep(STRESS_DELAY)
            return self._send(201, {"requestid": body.get("requestid")})
        return self._send(404, {"error": "unknown path"})

    def do_PUT(self):
        if not self._ua_ok():
            return self._send(403, {"error": "blocked"})
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        if u.path == "/v1/product":
            import uuid as _uuid

            key = f"{_uuid.uuid4().hex[:8]}.bin"
            with _lock:
                _uploaded.add(key)
            return self._send(200, {"image_path": key})
        return self._send(404, {"error": "unknown path"})


def main():
    p = argparse.ArgumentParser(description="하네스 검증용 목 서버")
    p.add_argument("--port", type=int, default=18080)
    p.add_argument(
        "--stress-delay",
        type=float,
        default=0.0,
        help="stress 응답 지연(초). SLO 위반 재현용",
    )
    p.add_argument(
        "--get-sleep-prob",
        type=float,
        default=0.0,
        help="user/product GET 지연 확률(2025 바이너리 400ms sleep 재현)",
    )
    p.add_argument("--get-sleep-sec", type=float, default=0.4)
    a = p.parse_args()
    global STRESS_DELAY, GET_SLEEP_PROB, GET_SLEEP_SEC
    STRESS_DELAY = a.stress_delay
    GET_SLEEP_PROB = a.get_sleep_prob
    GET_SLEEP_SEC = a.get_sleep_sec
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    print(
        f"[mock] listening on :{a.port} stress_delay={STRESS_DELAY} "
        f"get_sleep={GET_SLEEP_PROB}@{GET_SLEEP_SEC}s"
    )
    srv.serve_forever()


if __name__ == "__main__":
    main()
