# SPEC: product 앱 (Go / Gin)

> 구현 예정. 아래 계약대로 작성한다. (현재는 구조만)

- `POST /v1/product` → 201. body: requestid, uuid, id, name, price. MySQL insert.
- `GET /v1/product?id=&requestid=&uuid=` → 200. id로 조회 (동일 id 반복 요청 빈번 → 캐싱 여지).
- `PUT /v1/product` → 200. id + small image file. 이미지를 S3 업로드 후 image_path 갱신.
- `GET /healthcheck` → 200.
- 포트 8080. env: MYSQL_* (user와 동일) + S3 버킷/리전.
- SLO: 0.2s.

테이블:
```sql
CREATE TABLE product (id VARCHAR(255) NOT NULL, name VARCHAR(255) NOT NULL,
  price FLOAT(8) NOT NULL, image_path VARCHAR(500) DEFAULT NULL, PRIMARY KEY (id));
```
이미지 다운로드는 `<endpoint>/images/<object>` 경로로 제공(인프라 측 라우팅).
