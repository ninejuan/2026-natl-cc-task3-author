#!/usr/bin/env python3
"""경기 시뮬레이터 (task3-author).

시나리오 하나를 "경기처럼" 원샷으로 돌린다:
  1. 노드 수 샘플러(cost ratio 용)를 백그라운드로 띄운다
  2. 시나리오대로 트래픽을 주입한다
  3. 주입이 끝나면 채점기를 돌려 results 를 만든다
  4. 요청로그·노드로그·results 를 runs/<시나리오>_<시각>/ 로 아카이브한다

사용:
    python3 loadgen/race.py --scenario 2025-plus20 --endpoint https://xxx --student-id 12345
    python3 loadgen/race.py --scenario smoke --endpoint http://localhost:8080 --node-source ec2

여러 시나리오를 순차로 돌릴 수도 있다:
    python3 loadgen/race.py --scenario smoke,2025-replay,2025-plus20 --endpoint https://xxx
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scenario import load_scenario

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "logs"
RUNDIR = ROOT / "runs"
PYTHON = sys.executable


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_one(sc_name, args):
    sc = load_scenario(sc_name)
    stamp = now_stamp()
    print("=" * 72)
    print(sc.summary())
    print("=" * 72)

    LOGDIR.mkdir(parents=True, exist_ok=True)

    # 노드 샘플러는 주입 구간 + 여유를 커버해야 cost ratio 평균이 정확하다.
    sample_duration = sc.duration + sc.warmup + 30
    nodes_cmd = [
        PYTHON,
        str(ROOT / "loadgen" / "nodes.py"),
        "--student-id",
        args.student_id,
        "--duration",
        str(sample_duration),
        "--interval",
        str(args.node_interval),
        "--source",
        args.node_source,
    ]
    if args.node_source == "ec2":
        nodes_cmd += [
            "--tag-key",
            args.tag_key,
            "--tag-value",
            args.tag_value,
            "--region",
            args.region,
        ]

    nodes_proc = None
    if not args.no_nodes:
        print(
            f"[race] node sampler 시작 (source={args.node_source}, {sample_duration:.0f}s)"
        )
        nodes_proc = subprocess.Popen(
            nodes_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )

    load_cmd = [
        PYTHON,
        str(ROOT / "loadgen" / "main.py"),
        "--scenario",
        sc_name,
        "--endpoint",
        args.endpoint,
        "--student-id",
        args.student_id,
    ]
    if not args.verify_ssl:
        load_cmd.append("--no-verify-ssl")

    t0 = time.time()
    load_rc = subprocess.call(load_cmd)
    elapsed = time.time() - t0
    print(f"[race] 주입 종료 ({elapsed:.0f}s, rc={load_rc})")

    if nodes_proc is not None:
        # 주입이 끝났으면 샘플러도 정리한다(남은 시간을 기다리지 않는다).
        nodes_proc.terminate()
        try:
            nodes_proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            nodes_proc.kill()
        print("[race] node sampler 종료")

    grade_cmd = [
        PYTHON,
        str(ROOT / "grader" / "main.py"),
        "--student-id",
        args.student_id,
    ]
    print("[race] 채점 시작")
    grade_rc = subprocess.call(grade_cmd)

    run_dir = RUNDIR / f"{sc.name}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    for pattern in (
        f"requests_{args.student_id}_latest.jsonl",
        f"nodes_{args.student_id}_latest.jsonl",
        f"results_{args.student_id}.log",
    ):
        src = LOGDIR / pattern
        if src.exists():
            shutil.copy2(src, run_dir / Path(pattern).name)
    meta = {
        "scenario": sc.name,
        "description": sc.description,
        "endpoint": args.endpoint,
        "student_id": args.student_id,
        "duration": sc.duration,
        "warmup": sc.warmup,
        "concurrency": sc.concurrency,
        "peak_stress_rps": round(sc.peak_stress_rps, 2),
        "phases": [
            {
                "name": p.name,
                "duration": p.duration,
                "total_rps": p.total_rps,
                "stress_rps": round(p.stress_rps, 2),
                "stress_lengths": p.stress_lengths,
            }
            for p in sc.phases
        ],
        "started_utc": stamp,
        "elapsed_s": round(elapsed, 1),
        "loadgen_rc": load_rc,
        "grader_rc": grade_rc,
    }
    with open(run_dir / "meta.json", "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)
    print(f"[race] 아카이브: {run_dir}")
    return run_dir, grade_rc


def parse_args():
    p = argparse.ArgumentParser(description="task3 경기 시뮬레이터 (원샷)")
    p.add_argument(
        "--scenario", required=True, help="시나리오 이름. 쉼표로 여러 개 순차 실행 가능"
    )
    p.add_argument(
        "--endpoint",
        default=os.getenv("TARGET_ENDPOINT", ""),
        help="선수 단일 엔드포인트",
    )
    p.add_argument("--student-id", default=os.getenv("STUDENT_ID", "00000"))
    p.add_argument("--node-source", choices=["kubectl", "ec2"], default="kubectl")
    p.add_argument("--node-interval", type=float, default=10)
    p.add_argument(
        "--no-nodes",
        action="store_true",
        help="노드 샘플링 생략(로컬 앱 테스트용 — cost 는 채점 불가)",
    )
    p.add_argument("--tag-key", default="eks:nodegroup-name")
    p.add_argument("--tag-value", default="*")
    p.add_argument("--region", default=os.getenv("AWS_REGION", "ap-northeast-2"))
    p.add_argument("--no-verify-ssl", dest="verify_ssl", action="store_false")
    p.add_argument(
        "--gap",
        type=float,
        default=60,
        help="시나리오 연속 실행 시 사이 대기(초). stress CPU 부채 소진용",
    )
    p.set_defaults(verify_ssl=True)
    return p.parse_args()


def main():
    args = parse_args()
    if not args.endpoint:
        raise SystemExit("error: --endpoint (또는 TARGET_ENDPOINT) 가 필요합니다.")

    names = [s.strip() for s in args.scenario.split(",") if s.strip()]
    results = []
    for i, name in enumerate(names):
        if i > 0 and args.gap > 0:
            print(f"[race] 다음 시나리오까지 {args.gap:.0f}s 대기 (부채 소진)")
            time.sleep(args.gap)
        results.append(run_one(name, args))

    print("\n" + "=" * 72)
    print("[race] 완료한 실행")
    for run_dir, rc in results:
        print(f"  {run_dir.name}  (grader rc={rc})")
        res = run_dir / f"results_{args.student_id}.log"
        if res.exists():
            for line in res.read_text(encoding="utf-8").splitlines():
                if line.startswith("TOTAL"):
                    print(f"    {line}")


if __name__ == "__main__":
    main()
