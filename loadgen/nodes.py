#!/usr/bin/env python3
"""노드 수 샘플러 (cost ratio 용).

트래픽 주입 구간 동안 EKS 워커 노드(EC2) 수를 주기적으로 샘플링해
JSONL({ts, nodes}) 로 남긴다. grader 가 이 파일의 평균으로 cost ratio 를 계산한다.

측정 대상은 EC2 워커 노드만 (guide.md 1.1). 두 가지 소스를 지원한다:
  - kubectl : `kubectl get nodes` 의 Ready 워커 수 (기본, EKS 컨트롤플레인은 관리형이라 미포함)
  - ec2     : ASG/태그 기반 running 인스턴스 수 (aws CLI)

loadgen 과 병렬로 실행한다:
    python3 loadgen/nodes.py --student-id 12345 --duration 300 &
    python3 loadgen/main.py  --student-id 12345 --duration 300 --endpoint https://...
"""

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def count_kubectl():
    """kubectl get nodes 에서 Ready 워커 노드 수를 센다."""
    try:
        out = subprocess.run(
            ["kubectl", "get", "nodes", "--no-headers"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        ).stdout
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return None
    count = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "Ready" in parts[1] and "NotReady" not in parts[1]:
            count += 1
    return count


def count_ec2(tag_key, tag_value, region):
    """aws ec2 describe-instances 로 running 워커 수를 센다 (태그 필터)."""
    filters = [
        "Name=instance-state-name,Values=running",
        f"Name=tag:{tag_key},Values={tag_value}",
    ]
    cmd = [
        "aws",
        "ec2",
        "describe-instances",
        "--region",
        region,
        "--filters",
        *filters,
        "--query",
        "length(Reservations[].Instances[])",
        "--output",
        "text",
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, check=True
        ).stdout.strip()
        return int(out) if out and out != "None" else 0
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        ValueError,
    ):
        return None


def parse_args():
    p = argparse.ArgumentParser(description="task3 node sampler for cost ratio")
    p.add_argument("--student-id", default=os.getenv("STUDENT_ID", "00000"))
    p.add_argument("--duration", type=float, default=300, help="샘플링 시간(초)")
    p.add_argument("--interval", type=float, default=10, help="샘플 간격(초)")
    p.add_argument("--source", choices=["kubectl", "ec2"], default="kubectl")
    p.add_argument(
        "--tag-key",
        default="eks:nodegroup-name",
        help="ec2 소스일 때 워커 노드 식별 태그 키",
    )
    p.add_argument("--tag-value", default="*", help="ec2 소스일 때 태그 값")
    p.add_argument("--region", default=os.getenv("AWS_REGION", "ap-northeast-2"))
    p.add_argument(
        "--logdir", default=str(Path(__file__).resolve().parent.parent / "logs")
    )
    return p.parse_args()


def main():
    args = parse_args()
    logdir = Path(args.logdir)
    logdir.mkdir(parents=True, exist_ok=True)
    out_path = logdir / f"nodes_{args.student_id}_{now_iso()}.jsonl"

    print(
        f"[nodes] source={args.source} duration={args.duration}s interval={args.interval}s"
    )
    deadline = time.monotonic() + args.duration
    with open(out_path, "w", encoding="utf-8") as fp:
        while time.monotonic() < deadline:
            if args.source == "kubectl":
                n = count_kubectl()
            else:
                n = count_ec2(args.tag_key, args.tag_value, args.region)
            if n is not None:
                fp.write(json.dumps({"ts": time.time(), "nodes": n}) + "\n")
                fp.flush()
                print(f"[nodes] {datetime.now().strftime('%H:%M:%S')} nodes={n}")
            time.sleep(args.interval)

    latest = logdir / f"nodes_{args.student_id}_latest.jsonl"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(out_path.name)
    except OSError:
        pass
    print(f"[nodes] samples written: {out_path}")


if __name__ == "__main__":
    main()
