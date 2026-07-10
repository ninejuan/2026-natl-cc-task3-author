#!/usr/bin/env python3
"""채점기 (task3-author).

loadgen 이 남긴 JSONL 요청 로그 + (cost 용) 노드 수 샘플을 읽어
`results_<비번호>.log` 를 생성하고 guide.md 기준 40점을 집계한다.

채점 구조 (guide.md 0장, 총 40점)
  1. 비정상 요청 처리   4점  = image 처리율(2) + 비정상요청 403/404(2)
  2. 고가용성           12점 = (user/product/stress) availability
  3. 성능 효율성        12점 = (user/product/stress) performance
  4. 비용 최적화        12점 = cost ratio (performance 3종 ≥30% 게이트)

측정 정의
  - availability = 5초 내 2xx / 전체 × 100   (guide.md 3.1)
  - performance  = SLO 내 응답 / 전체 × 100  (guide.md 3.2)
      user/product ≤ 0.2s, stress ≤ 1.0s
  - image 처리율 = /images 다운로드 2xx / 전체
  - 비정상 요청  = bad_email→403 + unknown_path→404 + malicious_header→403 정확도
  - cost ratio   = 트래픽 구간 평균 EC2 노드 수 / baseline(2)
"""

import argparse
import glob
import json
import os
from pathlib import Path

# ---- guide.md 임계값 --------------------------------------------------------
SLO_SECONDS = {"user": 0.2, "product": 0.2, "stress": 1.0}
AVAILABILITY_TIMEOUT = 5.0  # 5초 내 2xx (guide.md 3.1)

# availability / performance: 8단계 × 0.5점 (guide.md 3장)
AP_THRESHOLDS = [90.0, 87.5, 85.0, 82.5, 80.0, 70.0, 50.0, 30.0]
AP_STEP_POINT = 0.5

# image / 비정상요청: 4단계 × 0.5점 (guide.md 4장)
ABNORMAL_THRESHOLDS = [90.0, 85.0, 80.0, 50.0]
ABNORMAL_STEP_POINT = 0.5

# cost ratio: 12단계 누적 (guide.md 1.2). (상한 ratio, 점수)
COST_TABLE = [
    (1.00, 12),
    (1.25, 11),
    (1.50, 10),
    (1.75, 9),
    (2.00, 8),
    (2.25, 7),
    (2.50, 6),
    (2.75, 5),
    (3.00, 4),
    (3.25, 3),
    (3.50, 2),
    (3.75, 1),
]
COST_BASELINE_NODES = 2
COST_GATE_PERF = 30.0  # performance 3종 ≥30% 게이트
COST_MIN_RATIO = 0.50  # ratio < 0.50 이면 비용 전체 0점


def step_score(pct, thresholds, step_point):
    """누적 계단 점수: 통과한 임계값 개수 × step_point."""
    return sum(step_point for t in thresholds if pct >= t)


def is_2xx(status):
    return 200 <= status < 300


def load_records(log_path):
    recs = []
    with open(log_path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


def compute_availability_performance(recs):
    """api 별 availability / performance (%) 계산. normal 트래픽만 대상."""
    out = {}
    for api in ("user", "product", "stress"):
        rows = [r for r in recs if r.get("api") == api and r.get("kind") == "normal"]
        total = len(rows)
        if total == 0:
            out[api] = {"availability": 0.0, "performance": 0.0, "total": 0}
            continue
        avail_ok = sum(
            1
            for r in rows
            if is_2xx(r.get("status", 0))
            and r.get("latency_s", 1e9) <= AVAILABILITY_TIMEOUT
        )
        slo = SLO_SECONDS[api]
        perf_ok = sum(
            1
            for r in rows
            if is_2xx(r.get("status", 0)) and r.get("latency_s", 1e9) <= slo
        )
        out[api] = {
            "availability": avail_ok / total * 100.0,
            "performance": perf_ok / total * 100.0,
            "total": total,
        }
    return out


def compute_image_rate(recs):
    rows = [r for r in recs if r.get("kind") == "image"]
    total = len(rows)
    if total == 0:
        return 0.0, 0
    ok = sum(1 for r in rows if is_2xx(r.get("status", 0)))
    return ok / total * 100.0, total


def compute_exception_rate(recs):
    """비정상 요청이 기대 코드로 차단되는 비율.

    bad_email → 403, malicious_header → 403, unknown_path → 404.
    """
    expected = {"bad_email": 403, "unknown_path": 404, "malicious_header": 403}
    rows = [r for r in recs if r.get("kind") in expected]
    total = len(rows)
    if total == 0:
        return 0.0, 0
    ok = sum(1 for r in rows if r.get("status") == expected[r["kind"]])
    return ok / total * 100.0, total


def load_node_samples(path):
    """노드 수 샘플 파일(JSONL: {ts, nodes}) 을 읽어 평균 EC2 노드 수 반환."""
    if not path or not os.path.exists(path):
        return None, 0
    counts = []
    with open(path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                counts.append(float(rec["nodes"]))
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                continue
    if not counts:
        return None, 0
    return sum(counts) / len(counts), len(counts)


def compute_cost_score(avg_nodes, ap):
    """cost ratio 점수 + ratio. 게이트/하한 반영."""
    if avg_nodes is None:
        return 0, None, "no node samples"

    ratio = avg_nodes / COST_BASELINE_NODES

    # 성능 게이트: 3종 모두 ≥30% 여야 비용 점수 인정.
    gate_ok = all(
        ap[a]["performance"] >= COST_GATE_PERF for a in ("user", "product", "stress")
    )
    if not gate_ok:
        return 0, ratio, "performance gate <30%"

    if ratio < COST_MIN_RATIO:
        return 0, ratio, "ratio < 0.50 (under-provisioned)"

    for upper, score in COST_TABLE:
        if ratio <= upper:
            return score, ratio, "ok"
    return 0, ratio, "ratio > 3.75"


def find_latest_log(logdir, student_id):
    latest = Path(logdir) / f"requests_{student_id}_latest.jsonl"
    if latest.exists():
        return str(latest)
    pattern = str(Path(logdir) / f"requests_{student_id}_*.jsonl")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def render_results(student_id, ap, image_rate, exc_rate, cost_score, ratio, cost_note):
    """results_<비번호>.log 본문 생성 (guide.md 5장 키 매핑)."""
    avail_score = sum(
        step_score(ap[a]["availability"], AP_THRESHOLDS, AP_STEP_POINT)
        for a in ("user", "product", "stress")
    )
    perf_score = sum(
        step_score(ap[a]["performance"], AP_THRESHOLDS, AP_STEP_POINT)
        for a in ("user", "product", "stress")
    )
    image_score = step_score(image_rate, ABNORMAL_THRESHOLDS, ABNORMAL_STEP_POINT)
    exc_score = step_score(exc_rate, ABNORMAL_THRESHOLDS, ABNORMAL_STEP_POINT)
    abnormal_score = image_score + exc_score
    total = abnormal_score + avail_score + perf_score + cost_score

    lines = []
    lines.append(f"# results_{student_id}.log")
    lines.append("# task3 System Operation 자동 채점 결과 (총 40점)")
    lines.append("")
    lines.append("## 1. 비정상 요청 처리 (4점)")
    lines.append(f"image download    : {image_rate:6.2f}%  -> {image_score:.1f}/2.0")
    lines.append(f"Exception Handling: {exc_rate:6.2f}%  -> {exc_score:.1f}/2.0")
    lines.append(f"subtotal          : {abnormal_score:.1f}/4.0")
    lines.append("")
    lines.append("## 2. 고가용성 및 안정성 (12점) — 5초 내 2xx")
    for a in ("user", "product", "stress"):
        s = step_score(ap[a]["availability"], AP_THRESHOLDS, AP_STEP_POINT)
        lines.append(
            f"({a}) availability : {ap[a]['availability']:6.2f}%  -> {s:.1f}/4.0  (n={ap[a]['total']})"
        )
    lines.append(f"subtotal          : {avail_score:.1f}/12.0")
    lines.append("")
    lines.append("## 3. 성능 효율성 (12점) — SLO 내 응답")
    for a in ("user", "product", "stress"):
        s = step_score(ap[a]["performance"], AP_THRESHOLDS, AP_STEP_POINT)
        lines.append(
            f"({a}) performance : {ap[a]['performance']:6.2f}%  -> {s:.1f}/4.0  (SLO {SLO_SECONDS[a]}s)"
        )
    lines.append(f"subtotal          : {perf_score:.1f}/12.0")
    lines.append("")
    lines.append("## 4. 비용 최적화 (12점)")
    ratio_str = f"{ratio:.3f}" if ratio is not None else "N/A"
    lines.append(
        f"cost ratio        : {ratio_str}  (baseline={COST_BASELINE_NODES} nodes)  -> {cost_score:.1f}/12.0"
    )
    lines.append(f"  note            : {cost_note}")
    lines.append("")
    lines.append("## 총점")
    lines.append(f"TOTAL             : {total:.1f}/40.0")
    return "\n".join(lines) + "\n", total


def parse_args():
    p = argparse.ArgumentParser(description="task3 grader")
    p.add_argument("--student-id", default=os.getenv("STUDENT_ID", "00000"))
    p.add_argument(
        "--logdir", default=str(Path(__file__).resolve().parent.parent / "logs")
    )
    p.add_argument(
        "--log", default=None, help="요청 로그 경로 (미지정 시 최신 자동 탐색)"
    )
    p.add_argument(
        "--nodes-log",
        default=None,
        help="노드 수 샘플 JSONL (미지정 시 logdir/nodes_<id>_latest.jsonl)",
    )
    p.add_argument(
        "--out", default=None, help="results 출력 경로 (기본 logdir/results_<id>.log)"
    )
    return p.parse_args()


def main():
    args = parse_args()

    log_path = args.log or find_latest_log(args.logdir, args.student_id)
    if not log_path or not os.path.exists(log_path):
        raise SystemExit(f"error: 요청 로그를 찾을 수 없습니다 (logdir={args.logdir}).")

    nodes_log = args.nodes_log or str(
        Path(args.logdir) / f"nodes_{args.student_id}_latest.jsonl"
    )

    recs = load_records(log_path)
    if not recs:
        raise SystemExit(f"error: 로그가 비어 있습니다: {log_path}")

    ap = compute_availability_performance(recs)
    image_rate, image_n = compute_image_rate(recs)
    exc_rate, exc_n = compute_exception_rate(recs)
    avg_nodes, node_samples = load_node_samples(nodes_log)
    cost_score, ratio, cost_note = compute_cost_score(avg_nodes, ap)

    body, total = render_results(
        args.student_id, ap, image_rate, exc_rate, cost_score, ratio, cost_note
    )

    out_path = args.out or str(Path(args.logdir) / f"results_{args.student_id}.log")
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(body)

    print(body)
    print(f"[grader] source log   : {log_path}  (records={len(recs)})")
    print(f"[grader] node samples : {node_samples} (avg={avg_nodes})")
    print(f"[grader] results       : {out_path}")
    print(f"[grader] TOTAL         : {total:.1f}/40.0")


if __name__ == "__main__":
    main()
