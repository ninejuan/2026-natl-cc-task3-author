package main

import (
	"log"
	"os"

	"stress/api"

	"github.com/gin-gonic/gin"
)

// stress 앱 — 순수 CPU 부하 생성기.
// 2025 제공 바이너리 리버싱 결과를 그대로 재현한다:
//   요청 본문 bind → AES-256-GCM 프리앰블(nonce는 crypto/rand) → base64 →
//   고정 4개 goroutine 이 각각 length 회 math.Pow(2,100) 반복.
// DB 없음. SLO 1.0s.

func main() {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Logger(), gin.Recovery())

	r.GET("/healthcheck", api.Healthcheck)
	r.POST("/v1/stress", api.PostStress)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("stress listening on :%s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatal(err)
	}
}
