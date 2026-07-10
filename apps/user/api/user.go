package api

import (
	"database/sql"
	"net/http"

	"github.com/gin-gonic/gin"
)

// UserRequest — POST /v1/user 본문 계약.
// requestid·uuid 는 변조 방지 계약이라 그대로 에코한다.
type UserRequest struct {
	RequestID string `json:"requestid"`
	UUID      string `json:"uuid"`
	ID        string `json:"id"`
	Username  string `json:"username"`
	Email     string `json:"email"`
}

type Handler struct {
	DB *sql.DB
}

func New(db *sql.DB) *Handler {
	return &Handler{DB: db}
}

// PostUser — user 레코드 insert. 이메일 형식 검증은 앱이 아니라 WAF 레벨에서
// 처리하므로(guide.md 4.2), 여기서는 포맷 검증을 하지 않는다.
func (h *Handler) PostUser(c *gin.Context) {
	var req UserRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	if req.ID == "" || req.Username == "" || req.Email == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "id, username, email required"})
		return
	}

	_, err := h.DB.Exec(
		"INSERT INTO user (id, username, email) VALUES (?, ?, ?) "+
			"ON DUPLICATE KEY UPDATE username=VALUES(username), email=VALUES(email)",
		req.ID, req.Username, req.Email,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert failed"})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"requestid": req.RequestID,
		"uuid":      req.UUID,
		"id":        req.ID,
		"username":  req.Username,
		"email":     req.Email,
	})
}

// GetUser — email 로 조회. requestid·uuid 는 에코.
func (h *Handler) GetUser(c *gin.Context) {
	email := c.Query("email")
	if email == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "email required"})
		return
	}

	var id, username, foundEmail string
	err := h.DB.QueryRow(
		"SELECT id, username, email FROM user WHERE email = ? LIMIT 1", email,
	).Scan(&id, &username, &foundEmail)
	if err == sql.ErrNoRows {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query failed"})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"requestid": c.Query("requestid"),
		"uuid":      c.Query("uuid"),
		"id":        id,
		"username":  username,
		"email":     foundEmail,
	})
}

func (h *Handler) Healthcheck(c *gin.Context) {
	if err := h.DB.Ping(); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "db unavailable"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}
