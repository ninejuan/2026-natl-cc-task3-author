package main

import (
	"log"
	"os"

	"user/api"
	"user/db"

	"github.com/gin-gonic/gin"
)

// user 앱 — MySQL(RDS) 백엔드. 2026 task.md 기준.
//   POST /v1/user      → 201, user insert
//   GET  /v1/user?email= → 200, email 조회
//   GET  /healthcheck  → 200
// 포트 8080. SLO 0.2s.

func main() {
	conn, err := db.Connect()
	if err != nil {
		log.Fatalf("db connect failed: %v", err)
	}
	defer conn.Close()

	h := api.New(conn)

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Logger(), gin.Recovery())

	r.GET("/healthcheck", h.Healthcheck)
	r.POST("/v1/user", h.PostUser)
	r.GET("/v1/user", h.GetUser)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("user listening on :%s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatal(err)
	}
}
