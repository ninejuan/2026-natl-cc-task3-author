# SPEC: stress 앱 (Go / Gin)

> 구현 예정. 아래 계약대로 작성한다. (현재는 구조만)

- `POST /v1/stress` → 201. body: requestid, uuid, length. length에 비례한 CPU 부하 발생.
- `GET /healthcheck` → 200.
- 포트 8080. access log stdout/stderr.
- SLO: 1.0s (user/product보다 느슨).
- DB 불필요 — 순수 CPU 연산 부하.
