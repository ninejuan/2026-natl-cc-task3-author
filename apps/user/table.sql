-- ============================================================================
-- table.sql — user 앱 테이블 스키마 (예시)
--
-- ★ 이 파일은 예시(sample)이며 자유롭게 커스텀 가능하다.
--   - 앱 코드는 테이블을 자동 생성(마이그레이션)하지 않는다. 스키마는 이 파일로
--     선수/출제자가 직접 RDS 에 반영한다.
--   - 컬럼 타입·인덱스·charset 등은 과제 요구에 맞게 바꿔도 된다.
--     단, user 앱이 사용하는 컬럼(id, username, email)은 유지해야 앱이 동작한다.
--   - 반영 예:  mysql -h <RDS_HOST> -u <USER> -p <DBNAME> < table.sql
--
-- 2026 스펙 기준. (2025 의 status_message 컬럼은 2026 에 없음)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `user` (
  `id`       VARCHAR(255) NOT NULL,
  `username` VARCHAR(255) NOT NULL,
  `email`    VARCHAR(255) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
