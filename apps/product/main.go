package main

import (
	"context"
	"log"
	"os"

	"product/api"
	"product/db"
	"product/storage"

	"github.com/gin-gonic/gin"
)

// product 앱 — MySQL(RDS) + S3. 2026 task.md 기준.
//   POST /v1/product      → 201, product insert
//   GET  /v1/product?id=  → 200, id 조회
//   PUT  /v1/product      → 200, 이미지 업로드(S3) 후 image_path 갱신
//   GET  /healthcheck     → 200
// 포트 8080. SLO 0.2s.

func main() {
	conn, err := db.Connect()
	if err != nil {
		log.Fatalf("db connect failed: %v", err)
	}
	defer conn.Close()

	uploader, err := storage.New(context.Background())
	if err != nil {
		log.Fatalf("s3 init failed: %v", err)
	}

	h := api.New(conn, uploader)

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Logger(), gin.Recovery())

	r.GET("/healthcheck", h.Healthcheck)
	r.POST("/v1/product", h.PostProduct)
	r.GET("/v1/product", h.GetProduct)
	r.PUT("/v1/product", h.PutProduct)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("product listening on :%s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatal(err)
	}
}
