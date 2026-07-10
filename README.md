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
| `apps/*/seed/` | 시드 데이터 (SQL 덤프·이미지, 커밋됨) | — |
| `build/` | 빌드 산출물 (바이너리) | — |
| `logs/` | 부하 주입 로그 저장 | — |

## 워크플로우

```bash
make build      # apps/* -> build/ (linux/amd64 바이너리 3종)
make publish    # build/* -> ../task3/provided/ (선수 레포로 바이너리 배포)

make deps       # loadgen 의존성(aiohttp) 설치. grader 는 표준 라이브러리만 쓴다.

# 부하 주입 — ENDPOINT 필수. STUDENT_ID/DURATION/MULTIPLIER/CONCURRENCY 로 조절.
make loadgen ENDPOINT=https://d123.cloudfront.net STUDENT_ID=12345 DURATION=1800 MULTIPLIER=1.5

# cost ratio 용 노드 수 샘플링 — loadgen 과 같은 구간에 병렬로 돌린다.
make nodes STUDENT_ID=12345 DURATION=1800 &

# 채점 — 위 두 로그를 읽어 results_<비번호>.log 생성 + 40점 집계.
make grade STUDENT_ID=12345
```

훈련 흐름: `make publish` → 선수 레포에서 `make up`으로 배포 → (`make nodes &` + `make loadgen`)으로 부하 → `make grade`로 채점 → 점수/SLO/노드수 확인.

## 채점 파이프라인 (40점)

부하와 채점은 두 단계로 나뉜다. `loadgen` 은 트래픽을 쏘고 요청별 결과를 JSONL 로그로만 남긴다. 점수 계산은 전부 `grader` 가 한다. 실제 대회에서 채점 플랫폼이 값을 계산해 로그에 적는 구조(guide.md 5장)를 그대로 따른 것이다.

- **loadgen** (`loadgen/main.py`) — user/product/stress + 이미지 다운로드 혼합 트래픽을 aiohttp 로 비동기 주입한다. 정상 요청뿐 아니라 잘못된 이메일(→403 기대), 미존재 경로(→404 기대), 그리고 악성 요청도 섞는다. 악성 요청은 **User-Agent 헤더를 뺀** 형태로, 선수 시스템의 WAF 가 403 으로 막아야 한다. 이 패턴은 2025 WAF 로그에서 실제 BLOCK 된 `AWSManagedRulesCommonRuleSet` / `NoUserAgent_HEADER` 실측에 근거한다.
- **nodes** (`loadgen/nodes.py`) — 주입 구간 동안 EKS 워커(EC2) 노드 수를 주기적으로 샘플링한다. cost ratio 는 이 평균값을 쓴다. `kubectl get nodes` 기본, `--source ec2` 로 aws CLI 도 가능하다.
- **grader** (`grader/main.py`) — 요청 로그와 노드 샘플을 읽어 네 항목을 집계한다.
  - availability (12): 5초 내 2xx 비율. 임계 90/87.5/85/82.5/80/70/50/30%.
  - performance (12): SLO 내 응답 비율(user·product ≤0.2s, stress ≤1.0s). 동일 임계.
  - 비정상 요청 처리 (4): 이미지 다운로드 성공률 + 403/404 정확도. 임계 90/85/80/50%.
  - cost ratio (12): 평균 노드 수 / 2. 1.0 이하 만점, 0.5 미만 0점. **단 performance 3종이 모두 30% 이상일 때만 점수를 준다.**

트래픽 규모는 2025-game ALB 로그 분석값을 기준(multiplier 1.0)으로 잡고, `--multiplier` 로 1.0~2.0배 사이에서 조절한다.

## demo 앱 API 계약 (2026 기준)

- **user**: `POST /v1/user`(201), `GET /v1/user?email=`(200), `GET /healthcheck`. MySQL 연결(`MYSQL_*` env).
- **product**: `POST /v1/product`(201), `GET /v1/product?id=`(200), `PUT /v1/product`(이미지 업로드→S3, 200), `GET /healthcheck`. MySQL + S3.
- **stress**: `POST /v1/stress`(length만큼 CPU 부하, 201), `GET /healthcheck`.
- 공통: 8080 포트, 요청에 `requestid`·`uuid` 포함, access log는 stdout/stderr.

> user·product 는 2026 과제지(task.md) 계약에 맞춘 mock 이다. 반면 **stress 는 2025 지급 바이너리를 리버싱한 로직을 그대로 재현**했다: 요청마다 AES-256-GCM 프리앰블(nonce는 crypto/rand)을 거친 뒤, 고정 4개 goroutine 이 각각 `length` 회 `math.Pow(2,100)` 을 반복한다. 그래서 CPU 부하가 `length` 에 선형 비례한다(로컬 측정: length 10M → 0.15s, 50M → 0.77s). SLO·채점 흐름 훈련이 목적이며, API 계약·상태코드는 과제지와 일치시킨다.

## 테이블 스키마 & 시드 데이터

앱은 테이블을 자동 생성하지 않는다. 스키마는 각 앱의 `table.sql` 로 직접 반영한다. 이 파일들은 예시이고 커스텀 가능하며, 맨 위 주석에 그 취지를 적어 뒀다.

- `apps/user/table.sql` — user(id, username, email)
- `apps/product/table.sql` — product(id, name, price, image_path)

```bash
mysql -h <RDS_HOST> -u <USER> -p <DBNAME> < apps/user/table.sql
mysql -h <RDS_HOST> -u <USER> -p <DBNAME> < apps/product/table.sql
```

시드 데이터는 각 앱 밑 `seed/` 에 미리 만들어 커밋해 뒀다. 2026 은 S3 이미지가 채점 요소라 이미지도 함께 둔다.

- `apps/user/seed/load_user.sql` — user 시드 (2025 덤프의 1.2배 규모)
- `apps/product/seed/load_product.sql` — product 시드 (`image_path` 포함)
- `apps/product/seed/images/<id>.jpg` — product 이미지

```bash
# RDS 반영:
mysql -h <RDS_HOST> -u <USER> -p <DBNAME> < apps/user/seed/load_user.sql
mysql -h <RDS_HOST> -u <USER> -p <DBNAME> < apps/product/seed/load_product.sql

# 이미지를 S3 에 업로드:
make seed-s3 S3_BUCKET=<bucket>
```

`load_product.sql` 은 INSERT 시점에 `image_path` 를 이미 담고 있다. object key 는 `<id>.jpg` 로, 이 값이 곧 이미지 파일명이자 앱의 `/images/<key>` 다운로드 경로다. 그래서 SQL 을 RDS 에 넣고 이미지를 S3 에 올리면(`make seed-s3` = `aws s3 sync`) 끝이다. 별도 image_path UPDATE 는 필요 없다.
