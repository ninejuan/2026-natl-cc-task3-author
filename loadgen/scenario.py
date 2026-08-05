#!/usr/bin/env python3
"""시나리오 로더 (task3-author).

경기 트래픽을 재현·변형하기 위한 시나리오 정의를 읽어 loadgen 이 쓸
페이즈 스케줄로 변환한다. 표준 라이브러리만 사용(JSON) — 현장 pip 실패 위험 회피.

시나리오 JSON 스키마
{
  "name": "2025-plus20",
  "description": "작년 피크 대비 stress +20%",
  "duration": 300,                  # 총 주입 시간(초). phases 합과 다르면 phases 우선.
  "warmup": 15,
  "concurrency": 64,
  "api_mix":  {"user": 0.40, "product": 0.45, "stress": 0.15},
  "kind_mix": {"normal": 0.82, "image": 0.08, "bad_email": 0.04,
               "unknown_path": 0.03, "malicious_header": 0.03},
  "stress_lengths": [200000, 500000, 1000000],
  "phases": [                       # 구간별 부하. 생략 시 total_rps 로 균일 주입.
    {"name": "ramp",  "duration": 60,  "total_rps": 40},
    {"name": "peak",  "duration": 180, "total_rps": 90,
     "stress_lengths": [900000]},   # 페이즈별 override 가능
    {"name": "spike", "duration": 60,  "total_rps": 150}
  ]
}

stress 실효 rps = total_rps × kind_mix[normal] × api_mix[stress] 이므로,
시나리오 작성 시 목표 stress rps 를 역산해 total_rps 를 정한다.
`python3 loadgen/scenario.py <파일>` 로 계산된 stress rps 를 검증할 수 있다.
"""

import json
import sys
from pathlib import Path

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"

DEFAULT_API_MIX = {"user": 0.40, "product": 0.45, "stress": 0.15}
DEFAULT_KIND_MIX = {
    "normal": 0.82,
    "image": 0.08,
    "bad_email": 0.04,
    "unknown_path": 0.03,
    "malicious_header": 0.03,
}
DEFAULT_STRESS_LENGTHS = [200_000, 500_000, 1_000_000]


class ScenarioError(ValueError):
    pass


class Phase:
    def __init__(self, name, duration, total_rps, stress_lengths, api_mix, kind_mix):
        self.name = name
        self.duration = duration
        self.total_rps = total_rps
        self.stress_lengths = stress_lengths
        self.api_mix = api_mix
        self.kind_mix = kind_mix

    @property
    def stress_rps(self):
        return (
            self.total_rps
            * self.kind_mix.get("normal", 0)
            * self.api_mix.get("stress", 0)
        )

    def __repr__(self):
        return (
            f"Phase({self.name}, {self.duration}s, total_rps={self.total_rps}, "
            f"stress_rps={self.stress_rps:.1f}, lengths={self.stress_lengths})"
        )


class Scenario:
    def __init__(self, raw):
        self.name = raw.get("name", "unnamed")
        self.description = raw.get("description", "")
        self.warmup = float(raw.get("warmup", 15))
        self.concurrency = int(raw.get("concurrency", 64))
        base_api = _norm_mix(raw.get("api_mix", DEFAULT_API_MIX), "api_mix")
        base_kind = _norm_mix(raw.get("kind_mix", DEFAULT_KIND_MIX), "kind_mix")
        base_lengths = raw.get("stress_lengths", DEFAULT_STRESS_LENGTHS)
        _check_lengths(base_lengths)

        phases_raw = raw.get("phases")
        if phases_raw:
            self.phases = [
                Phase(
                    name=p.get("name", f"phase{i + 1}"),
                    duration=float(p["duration"]),
                    total_rps=float(p["total_rps"]),
                    stress_lengths=_checked(p.get("stress_lengths", base_lengths)),
                    api_mix=_norm_mix(p["api_mix"], "api_mix")
                    if "api_mix" in p
                    else base_api,
                    kind_mix=_norm_mix(p["kind_mix"], "kind_mix")
                    if "kind_mix" in p
                    else base_kind,
                )
                for i, p in enumerate(phases_raw)
            ]
        else:
            total_rps = float(raw.get("total_rps", 40))
            self.phases = [
                Phase(
                    "flat",
                    float(raw.get("duration", 300)),
                    total_rps,
                    base_lengths,
                    base_api,
                    base_kind,
                )
            ]

    @property
    def duration(self):
        return sum(p.duration for p in self.phases)

    @property
    def peak_stress_rps(self):
        return max(p.stress_rps for p in self.phases)

    def phase_at(self, elapsed):
        """경과 시간(초)에 해당하는 페이즈. 범위를 넘으면 마지막 페이즈."""
        acc = 0.0
        for p in self.phases:
            acc += p.duration
            if elapsed < acc:
                return p
        return self.phases[-1]

    def summary(self):
        lines = [f"scenario: {self.name}"]
        if self.description:
            lines.append(f"  {self.description}")
        lines.append(
            f"  duration={self.duration:.0f}s warmup={self.warmup:.0f}s "
            f"concurrency={self.concurrency}"
        )
        for p in self.phases:
            lines.append(
                f"  - {p.name:8s} {p.duration:6.0f}s total_rps={p.total_rps:6.1f} "
                f"stress_rps={p.stress_rps:5.1f} lengths={p.stress_lengths}"
            )
        lines.append(f"  peak stress_rps = {self.peak_stress_rps:.1f}")
        return "\n".join(lines)


def _norm_mix(mix, label):
    if not isinstance(mix, dict) or not mix:
        raise ScenarioError(f"{label}: dict 여야 합니다")
    total = sum(mix.values())
    if total <= 0:
        raise ScenarioError(f"{label}: 가중치 합이 0보다 커야 합니다")
    return {k: v / total for k, v in mix.items()}


def _check_lengths(lengths):
    if not isinstance(lengths, list) or not lengths:
        raise ScenarioError("stress_lengths: 비어있지 않은 리스트여야 합니다")
    for v in lengths:
        if not isinstance(v, int) or v <= 0:
            raise ScenarioError(f"stress_lengths: 양의 정수여야 합니다 (got {v!r})")


def _checked(lengths):
    _check_lengths(lengths)
    return lengths


def resolve_path(name_or_path):
    """시나리오 이름 또는 경로를 실제 파일 경로로 해석."""
    p = Path(name_or_path)
    if p.exists():
        return p
    candidate = SCENARIO_DIR / f"{name_or_path}.json"
    if candidate.exists():
        return candidate
    available = (
        ", ".join(sorted(f.stem for f in SCENARIO_DIR.glob("*.json"))) or "(없음)"
    )
    raise ScenarioError(
        f"시나리오를 찾을 수 없습니다: {name_or_path}\n사용 가능: {available}"
    )


def load_scenario(name_or_path):
    path = resolve_path(name_or_path)
    with open(path, "r", encoding="utf-8") as fp:
        raw = json.load(fp)
    sc = Scenario(raw)
    if not sc.phases:
        raise ScenarioError("phases 가 비어 있습니다")
    return sc


def main():
    if len(sys.argv) < 2:
        names = sorted(f.stem for f in SCENARIO_DIR.glob("*.json"))
        print("사용법: python3 loadgen/scenario.py <시나리오|경로>")
        print("사용 가능:", ", ".join(names) if names else "(없음)")
        return
    for arg in sys.argv[1:]:
        print(load_scenario(arg).summary())
        print()


if __name__ == "__main__":
    main()
