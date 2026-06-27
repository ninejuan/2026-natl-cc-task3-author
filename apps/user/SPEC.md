# SPEC: user 앱 (Go / Gin)

> 구현 예정. 아래 계약대로 작성한다. (현재는 구조만)

- `POST /v1/user` → 201. body: requestid, uuid, username, email. MySQL `user` 테이블에 insert.
- `GET /v1/user?email=&requestid=&uuid=` → 200. email로 조회.
- `GET /healthcheck` → 200.
- 포트 8080. access log stdout/stderr.
- env: MYSQL_USER, MYSQL_PASSWORD, MYSQL_HOST, MYSQL_PORT, MYSQL_DBNAME.
- SLO: 0.2s.

테이블:
```sql
CREATE TABLE user (id VARCHAR(255) NOT NULL, username VARCHAR(255) NOT NULL,
  email VARCHAR(255) NOT NULL, PRIMARY KEY (id), UNIQUE KEY uk_username (username));
```
