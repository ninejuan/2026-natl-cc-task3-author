# task3-author — 출제자/훈련 측 도구

3과제(System Operation) 훈련을 위한 **출제자 측** 코드. 별도 GitHub 레포로 관리하며,
**선수 레포(`task3`)에는 절대 올리지 않는다**(답안지 성격: 앱 동작·채점 로직 노출 금지).

선수에게는 빌드된 **바이너리만** 전달된다(실제 대회와 동일).

## 구성

| 경로 | 내용 | 언어 |
|---|---|---|
| `apps/user`, `apps/product`, `apps/stress` | demo 앱 소스 (2026 API 계약 구현) | Go / Gin |
| `loadgen/` | 부하 주입기 (트래픽 생성) | Python / aiohttp |
| `grader/` | 채점기 (`results_<비번호>.log` 생성·집계) | Python |
| `build/` | 빌드 산출물 (바이너리) | — |
| `logs/` | 부하 주입 로그 저장 | — |

## 워크플로우

```bash
make build      # apps/* -> build/ (linux/amd64 바이너리 3종)
make publish    # build/* -> ../task3/provided/ (선수 레포로 바이너리 배포)

make loadgen    # 선수 엔드포인트에 트래픽 주입 (logs/ 에 기록)
make grade      # 주입 결과로 results_<비번호>.log 생성
```

훈련 흐름: `make publish` → 선수 레포에서 `make up`으로 배포 → `make loadgen`으로 부하 → `make grade`로 채점.

## demo 앱 API 계약 (2026 기준)

- **user**: `POST /v1/user`(201), `GET /v1/user?email=`(200), `GET /healthcheck`. MySQL 연결(`MYSQL_*` env).
- **product**: `POST /v1/product`(201), `GET /v1/product?id=`(200), `PUT /v1/product`(이미지 업로드→S3, 200), `GET /healthcheck`. MySQL + S3.
- **stress**: `POST /v1/stress`(length만큼 CPU 부하, 201), `GET /healthcheck`.
- 공통: 8080 포트, 요청에 `requestid`·`uuid` 포함, access log는 stdout/stderr.

> 실제 지급 바이너리와 100% 동일하진 않다. SLO·채점 흐름을 훈련하기 위한 mock이며, API 계약·상태코드는 과제지와 일치시킨다.
# 2026-natl-cc-task3-author
