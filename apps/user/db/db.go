package db

import (
	"database/sql"
	"fmt"
	"os"
	"time"

	_ "github.com/go-sql-driver/mysql"
)

// Connect — MYSQL_* 환경변수로 RDS(MySQL 8.0) 에 연결한다.
// user·product 공통 계약: MYSQL_USER / MYSQL_PASSWORD / MYSQL_HOST / MYSQL_PORT / MYSQL_DBNAME.
func Connect() (*sql.DB, error) {
	dsn := fmt.Sprintf(
		"%s:%s@tcp(%s:%s)/%s?parseTime=true&charset=utf8mb4&loc=UTC",
		os.Getenv("MYSQL_USER"),
		os.Getenv("MYSQL_PASSWORD"),
		os.Getenv("MYSQL_HOST"),
		envOr("MYSQL_PORT", "3306"),
		os.Getenv("MYSQL_DBNAME"),
	)

	var conn *sql.DB
	var err error
	// RDS 기동/네트워크 안정화 대기 — 최대 30초 재시도.
	for i := 0; i < 30; i++ {
		conn, err = sql.Open("mysql", dsn)
		if err == nil {
			if pingErr := conn.Ping(); pingErr == nil {
				break
			} else {
				err = pingErr
			}
		}
		time.Sleep(time.Second)
	}
	if err != nil {
		return nil, err
	}

	conn.SetMaxOpenConns(50)
	conn.SetMaxIdleConns(25)
	conn.SetConnMaxLifetime(5 * time.Minute)

	return conn, nil
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
