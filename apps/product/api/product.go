package api

import (
	"context"
	"database/sql"
	"fmt"
	"io"
	"net/http"
	"path/filepath"
	"time"

	"product/storage"

	"github.com/gin-gonic/gin"
)

// ProductRequest — POST /v1/product 본문 계약.
type ProductRequest struct {
	RequestID string  `json:"requestid"`
	UUID      string  `json:"uuid"`
	ID        string  `json:"id"`
	Name      string  `json:"name"`
	Price     float64 `json:"price"`
}

type Handler struct {
	DB *sql.DB
	S3 *storage.Uploader
}

func New(db *sql.DB, s3 *storage.Uploader) *Handler {
	return &Handler{DB: db, S3: s3}
}

// PostProduct — product insert.
func (h *Handler) PostProduct(c *gin.Context) {
	var req ProductRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	if req.ID == "" || req.Name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "id, name required"})
		return
	}

	_, err := h.DB.Exec(
		"INSERT INTO product (id, name, price) VALUES (?, ?, ?) "+
			"ON DUPLICATE KEY UPDATE name=VALUES(name), price=VALUES(price)",
		req.ID, req.Name, req.Price,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert failed"})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"requestid": req.RequestID,
		"uuid":      req.UUID,
		"id":        req.ID,
		"name":      req.Name,
		"price":     req.Price,
	})
}

// GetProduct — id 로 조회. 동일 id 반복 요청이 빈번하므로(SPEC) 캐싱 여지가 있으나,
// 캐싱은 인프라(CloudFront/앱 앞단) 책임이라 앱은 매번 조회한다.
func (h *Handler) GetProduct(c *gin.Context) {
	id := c.Query("id")
	if id == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "id required"})
		return
	}

	var name string
	var price float64
	var imagePath sql.NullString
	err := h.DB.QueryRow(
		"SELECT name, price, image_path FROM product WHERE id = ? LIMIT 1", id,
	).Scan(&name, &price, &imagePath)
	if err == sql.ErrNoRows {
		c.JSON(http.StatusNotFound, gin.H{"error": "product not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query failed"})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"requestid":  c.Query("requestid"),
		"uuid":       c.Query("uuid"),
		"id":         id,
		"name":       name,
		"price":      price,
		"image_path": imagePath.String,
	})
}

// PutProduct — id + 이미지 파일(multipart) 업로드. 이미지를 S3 에 올린 뒤
// product.image_path 를 갱신한다. 다운로드는 <endpoint>/images/<key>.
func (h *Handler) PutProduct(c *gin.Context) {
	id := c.PostForm("id")
	if id == "" {
		id = c.Query("id")
	}
	if id == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "id required"})
		return
	}

	fileHeader, err := c.FormFile("image")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "image file required"})
		return
	}
	f, err := fileHeader.Open()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot open upload"})
		return
	}
	defer f.Close()
	data, err := io.ReadAll(f)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot read upload"})
		return
	}

	ext := filepath.Ext(fileHeader.Filename)
	key := fmt.Sprintf("%s-%d%s", id, time.Now().UnixNano(), ext)
	contentType := fileHeader.Header.Get("Content-Type")
	if contentType == "" {
		contentType = "application/octet-stream"
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 15*time.Second)
	defer cancel()
	storedKey, err := h.S3.Put(ctx, key, data, contentType)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "s3 upload failed"})
		return
	}

	if _, err := h.DB.Exec(
		"UPDATE product SET image_path = ? WHERE id = ?", storedKey, id,
	); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "update failed"})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"requestid":  c.PostForm("requestid"),
		"uuid":       c.PostForm("uuid"),
		"id":         id,
		"image_path": storedKey,
	})
}

func (h *Handler) Healthcheck(c *gin.Context) {
	if err := h.DB.Ping(); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "db unavailable"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}
