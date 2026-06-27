# SPEC: 채점기 (Python)

> 구현 예정. **guide.md 채점항목 전체(40점)** 를 집계해야 한다. (현재는 구조만)

loadgen이 남긴 `../logs/` 요청 로그 + (cost용) 노드수 샘플을 읽어
`results_<비번호>.log`를 생성하고 점수를 집계한다.

## 산출 로그 필드 (results_<비번호>.log)
guide.md 5장 매핑과 일치:
- `email request validation`, `Exception Handling` — 비정상 요청 처리(4점)
- `(user/product/stress) availability` — 5초 내 2xx 성공률(12점)
- `(user/product/stress) performance` — SLO 내 응답률(12점). user·product ≤0.2s, stress ≤1.0s
- `cost ratio` — 비용(12점)

## 집계 로직 (guide.md 기준)
1. **availability** = 5초 내 2xx / 전체 × 100. 임계 90/87.5/.../30.
2. **performance** = SLO 이내 응답 / 전체 × 100. 동일 임계.
3. **image 처리율** = `/images/<obj>` 다운로드 성공률. 임계 90/85/80/50.
4. **비정상 요청 처리율** = 잘못된 email→403, 미존재 경로→404 정확도.
5. **cost ratio** = 트래픽 구간 **평균 EC2 노드 수 / baseline(2)**.
   - 노드 수는 주입 구간 동안 지속 측정한 샘플의 평균 (EC2 노드만).
   - 1.0 이하 만점, 0.5 미만 0점. 단 performance 3종 ≥30% 게이트.
   - 12단계 누적 채점 (guide.md 1.2 표).

## 노드 수 측정
- 주입 구간 동안 주기적으로 워커 노드 수 샘플링(예: EC2 describe / k8s get nodes).
- EC2 노드만 카운트 (RDS/NAT/ALB/EKS 컨트롤플레인 제외 — guide.md 1.1).

## 출력
- `results_<비번호>.log` (채점 원천)
- 항목별 점수 + 총점(40) 요약.
