#!/usr/bin/env python3
"""부하 주입기 (task3-author).

선수가 제출한 단일 엔드포인트에 user/product/stress + 이미지 다운로드 혼합
트래픽을 aiohttp 로 비동기 주입하고, 요청별 결과를 JSONL 로그로 남긴다.
채점기(grader/main.py)가 이 로그를 읽어 40점을 집계한다.

트래픽 종류
  - normal          : 정상 요청 (availability/performance 집계 대상)
  - image           : /images/<key> 다운로드 (image 처리율)
  - bad_email       : 잘못된 이메일 POST /v1/user → 선수 시스템이 403 이어야 함
  - unknown_path    : 미존재 경로 → 404 이어야 함
  - malicious_header: User-Agent 누락 요청 → WAF 가 403 차단해야 함
                      (근거: 2025 WAF 로그 AWSManagedRulesCommonRuleSet /
                       NoUserAgent_HEADER 실측 BLOCK)

트래픽 규모는 2025-game ALB 로그 기준을 1.0~2.0배로 조절 가능(--multiplier).
"""

import argparse
import asyncio
import json
import os
import random
import string
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

# ---- 로그 스키마 (grader 와 공유하는 계약) --------------------------------
# 한 줄당 JSON 객체:
#   ts        float  요청 시작 (epoch)
#   api       str    "user"|"product"|"stress"|"image"
#   kind      str    "normal"|"image"|"bad_email"|"unknown_path"|"malicious_header"
#   method    str
#   path      str
#   status    int    HTTP 상태코드 (연결 실패/타임아웃 시 0)
#   latency_s float  클라이언트 도착 기준 응답시간
#   error     str    (선택) 예외 메시지
SCHEMA_VERSION = 1

# ---- SLO (guide.md 3장) ---------------------------------------------------
SLO_SECONDS = {"user": 0.2, "product": 0.2, "stress": 1.0}

# ---- 2025-game 기준 트래픽 프로파일 (baseline = multiplier 1.0) -----------
# ALB 로그 분석 결과: user/product 는 빠르고 빈번, stress 는 드물지만 무겁다.
# API 혼합 비율(정상 트래픽 내에서).
API_MIX = {"user": 0.40, "product": 0.45, "stress": 0.15}
# 비정상/악성 트래픽 비율(전체 요청 대비). 나머지는 정상.
KIND_MIX = {
    "normal": 0.82,
    "image": 0.08,
    "bad_email": 0.04,
    "unknown_path": 0.03,
    "malicious_header": 0.03,
}
BASELINE_RPS = 40  # multiplier 1.0 일 때 목표 RPS (2025 ALB 평균 구간 근사)

DEFAULT_UA = "wsk-grader/1.0 (+aiohttp)"
BAD_EMAILS = ["gildong", "gildong@example", "no-at-sign.com", "a@b", "@nodomain"]
STRESS_LENGTHS = [200_000, 500_000, 1_000_000]  # 부하량 파라미터 (요청별)


def rand_id(n=12):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def pick_weighted(mapping):
    keys = list(mapping.keys())
    weights = list(mapping.values())
    return random.choices(keys, weights=weights, k=1)[0]


class LoadGen:
    def __init__(self, args, log_fp):
        self.args = args
        self.log_fp = log_fp
        self.base = args.endpoint.rstrip("/")
        self.sem = asyncio.Semaphore(args.concurrency)
        self.sent = 0
        self.lock = asyncio.Lock()
        # 업로드된 이미지 키를 기억해 /images 다운로드에 사용.
        self.image_keys = []
        # product id 풀 (GET 반복 조회 재현).
        self.product_ids = [rand_id(8) for _ in range(50)]

    async def write(self, rec):
        rec["schema"] = SCHEMA_VERSION
        line = json.dumps(rec, ensure_ascii=False)
        async with self.lock:
            self.log_fp.write(line + "\n")

    def _headers(self, kind):
        # 악성: User-Agent 헤더를 아예 제거 (NoUserAgent_HEADER 재현).
        if kind == "malicious_header":
            return {}
        return {"User-Agent": DEFAULT_UA}

    async def _record(self, session, api, kind, method, path, **kw):
        url = self.base + path
        headers = self._headers(kind)
        kw.setdefault("headers", {}).update(headers)
        t0 = time.perf_counter()
        status = 0
        err = None
        try:
            async with session.request(method, url, **kw) as resp:
                await resp.read()
                status = resp.status
        except asyncio.TimeoutError:
            err = "timeout"
        except aiohttp.ClientError as e:
            err = f"client:{type(e).__name__}"
        except Exception as e:  # noqa: BLE001 - 주입기는 모든 예외를 실패로 기록
            err = f"other:{type(e).__name__}"
        latency = time.perf_counter() - t0
        rec = {
            "ts": time.time(),
            "api": api,
            "kind": kind,
            "method": method,
            "path": path,
            "status": status,
            "latency_s": round(latency, 4),
        }
        if err:
            rec["error"] = err
        await self.write(rec)

    async def do_user_normal(self, session):
        rid, uid = rand_id(), str(uuid.uuid4())
        if random.random() < 0.5:
            body = {
                "requestid": rid,
                "uuid": uid,
                "id": rand_id(8),
                "username": rand_id(10),
                "email": f"{rand_id(6)}@example.com",
            }
            await self._record(session, "user", "normal", "POST", "/v1/user", json=body)
        else:
            q = f"/v1/user?email={rand_id(6)}@example.com&requestid={rid}&uuid={uid}"
            await self._record(session, "user", "normal", "GET", q)

    async def do_product_normal(self, session):
        rid, uid = rand_id(), str(uuid.uuid4())
        pid = random.choice(self.product_ids)
        r = random.random()
        if r < 0.3:
            body = {
                "requestid": rid,
                "uuid": uid,
                "id": pid,
                "name": rand_id(8),
                "price": round(random.uniform(1, 1000), 2),
            }
            await self._record(
                session, "product", "normal", "POST", "/v1/product", json=body
            )
        elif r < 0.9:
            # 동일 id 반복 조회 (캐싱 유도) — SLO 달성 관건.
            q = f"/v1/product?id={pid}&requestid={rid}&uuid={uid}"
            await self._record(session, "product", "normal", "GET", q)
        else:
            # 이미지 업로드 (PUT). 성공 시 키를 기억.
            data = aiohttp.FormData()
            data.add_field("id", pid)
            data.add_field("requestid", rid)
            data.add_field("uuid", uid)
            data.add_field(
                "image",
                os.urandom(2048),
                filename=f"{pid}.bin",
                content_type="application/octet-stream",
            )
            # PUT 은 별도 기록 후, 응답에서 image_path 를 파싱해 다운로드 풀에 추가.
            await self._put_image(session, pid, data)

    async def _put_image(self, session, pid, data):
        url = self.base + "/v1/product"
        t0 = time.perf_counter()
        status, err, key = 0, None, None
        try:
            async with session.put(
                url, data=data, headers={"User-Agent": DEFAULT_UA}
            ) as resp:
                text = await resp.text()
                status = resp.status
                if resp.status == 200:
                    try:
                        key = json.loads(text).get("image_path")
                    except json.JSONDecodeError:
                        key = None
        except Exception as e:  # noqa: BLE001
            err = f"other:{type(e).__name__}"
        latency = time.perf_counter() - t0
        rec = {
            "ts": time.time(),
            "api": "product",
            "kind": "normal",
            "method": "PUT",
            "path": "/v1/product",
            "status": status,
            "latency_s": round(latency, 4),
        }
        if err:
            rec["error"] = err
        await self.write(rec)
        if key:
            self.image_keys.append(key)

    async def do_stress_normal(self, session):
        rid, uid = rand_id(), str(uuid.uuid4())
        body = {"requestid": rid, "uuid": uid, "length": random.choice(STRESS_LENGTHS)}
        await self._record(session, "stress", "normal", "POST", "/v1/stress", json=body)

    async def do_image(self, session):
        # 업로드된 키가 있으면 그걸, 없으면 임의 키(존재하지 않을 수 있음)를 요청.
        if self.image_keys:
            key = random.choice(self.image_keys)
        else:
            key = f"{rand_id(8)}.bin"
        await self._record(session, "image", "image", "GET", f"/images/{key}")

    async def do_bad_email(self, session):
        rid, uid = rand_id(), str(uuid.uuid4())
        body = {
            "requestid": rid,
            "uuid": uid,
            "id": rand_id(8),
            "username": rand_id(10),
            "email": random.choice(BAD_EMAILS),
        }
        await self._record(session, "user", "bad_email", "POST", "/v1/user", json=body)

    async def do_unknown_path(self, session):
        await self._record(session, "user", "unknown_path", "GET", "/v1/none")

    async def do_malicious(self, session):
        # 정상처럼 보이는 요청이지만 User-Agent 를 제거 → WAF 가 403 차단해야 함.
        rid, uid = rand_id(), str(uuid.uuid4())
        q = f"/v1/user?email={rand_id(6)}@example.com&requestid={rid}&uuid={uid}"
        await self._record(session, "user", "malicious_header", "GET", q)

    async def dispatch(self, session):
        kind = pick_weighted(KIND_MIX)
        if kind == "normal":
            api = pick_weighted(API_MIX)
            if api == "user":
                await self.do_user_normal(session)
            elif api == "product":
                await self.do_product_normal(session)
            else:
                await self.do_stress_normal(session)
        elif kind == "image":
            await self.do_image(session)
        elif kind == "bad_email":
            await self.do_bad_email(session)
        elif kind == "unknown_path":
            await self.do_unknown_path(session)
        elif kind == "malicious_header":
            await self.do_malicious(session)

    async def worker(self, session, deadline, target_rps):
        # 각 워커는 목표 RPS/concurrency 를 나눠 가지며 포아송 간격으로 요청.
        interval = self.args.concurrency / max(target_rps, 1e-6)
        while time.monotonic() < deadline:
            async with self.sem:
                await self.dispatch(session)
                self.sent += 1
            await asyncio.sleep(
                random.expovariate(1.0 / interval) if interval > 0 else 0
            )

    async def run(self):
        target_rps = BASELINE_RPS * self.args.multiplier
        timeout = aiohttp.ClientTimeout(total=self.args.request_timeout)
        connector = aiohttp.TCPConnector(
            limit=self.args.concurrency * 2, ssl=self.args.verify_ssl
        )
        deadline = time.monotonic() + self.args.duration

        print(
            f"[loadgen] endpoint={self.base} duration={self.args.duration}s "
            f"multiplier={self.args.multiplier} target_rps≈{target_rps:.0f} "
            f"concurrency={self.args.concurrency}"
        )
        async with aiohttp.ClientSession(
            timeout=timeout, connector=connector
        ) as session:
            # 웜업: 앱 준비 대기.
            if self.args.warmup > 0:
                warm_deadline = time.monotonic() + self.args.warmup
                await asyncio.gather(
                    *[
                        self.worker(session, warm_deadline, target_rps * 0.3)
                        for _ in range(max(1, self.args.concurrency // 4))
                    ]
                )
            await asyncio.gather(
                *[
                    self.worker(session, deadline, target_rps)
                    for _ in range(self.args.concurrency)
                ]
            )
        print(f"[loadgen] done. sent={self.sent} log={self.log_fp.name}")


def parse_args():
    p = argparse.ArgumentParser(description="task3 load generator")
    p.add_argument(
        "--endpoint",
        default=os.getenv("TARGET_ENDPOINT", ""),
        help="선수 단일 엔드포인트 (예: https://example.org)",
    )
    p.add_argument(
        "--student-id",
        default=os.getenv("STUDENT_ID", "00000"),
        help="비번호 (로그 파일명에 사용)",
    )
    p.add_argument("--duration", type=float, default=300, help="총 주입 시간(초)")
    p.add_argument("--warmup", type=float, default=15, help="웜업 시간(초)")
    p.add_argument(
        "--multiplier",
        type=float,
        default=1.0,
        help="2025-game 기준 트래픽 배수 (1.0~2.0)",
    )
    p.add_argument("--concurrency", type=int, default=64, help="동시 워커 수")
    p.add_argument(
        "--request-timeout", type=float, default=10.0, help="요청 타임아웃(초)"
    )
    p.add_argument(
        "--no-verify-ssl",
        dest="verify_ssl",
        action="store_false",
        help="TLS 검증 비활성화 (자체서명 인증서용)",
    )
    p.add_argument(
        "--logdir", default=str(Path(__file__).resolve().parent.parent / "logs")
    )
    p.set_defaults(verify_ssl=True)
    return p.parse_args()


def main():
    args = parse_args()
    if not args.endpoint:
        raise SystemExit("error: --endpoint (또는 TARGET_ENDPOINT) 가 필요합니다.")
    if not (1.0 <= args.multiplier <= 2.0):
        print(
            f"[warn] multiplier={args.multiplier} 는 권장 범위(1.0~2.0)를 벗어납니다."
        )

    logdir = Path(args.logdir)
    logdir.mkdir(parents=True, exist_ok=True)
    log_path = logdir / f"requests_{args.student_id}_{now_iso()}.jsonl"

    with open(log_path, "w", encoding="utf-8") as fp:
        gen = LoadGen(args, fp)
        asyncio.run(gen.run())
    print(f"[loadgen] raw log written: {log_path}")
    # grader 가 최신 로그를 쉽게 찾도록 심볼릭 최신 포인터 갱신.
    latest = logdir / f"requests_{args.student_id}_latest.jsonl"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(log_path.name)
    except OSError:
        pass


if __name__ == "__main__":
    main()
