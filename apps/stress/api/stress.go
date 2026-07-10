package api

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"io"
	"math"
	"net/http"
	"sync"

	"github.com/gin-gonic/gin"
)

// StressRequest — 2025 바이너리 계약. length 가 CPU 부하량을 직접 결정한다.
type StressRequest struct {
	RequestID string `json:"requestid"`
	UUID      string `json:"uuid"`
	Length    int    `json:"length"`
}

// stressKey — AES-256 고정 키(32바이트). 2025 바이너리가 프리앰블에서
// AES-GCM 을 구성하던 동작을 재현하기 위한 것으로, 실제 암호학적 의미는 없다.
var stressKey = []byte("worldskills-2025-stress-key-32by")

// aesGCMPreamble — 요청마다 nonce(crypto/rand) 를 새로 만들어 payload 를
// AES-256-GCM 으로 봉인하고 base64 로 인코딩한다. 리버싱에서 확인된 프리앰블.
func aesGCMPreamble(payload []byte) (string, error) {
	block, err := aes.NewCipher(stressKey)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}
	sealed := gcm.Seal(nonce, nonce, payload, nil)
	return base64.StdEncoding.EncodeToString(sealed), nil
}

// burn — goroutine 본체. 2025 PostStress.func1 재현:
//
//	for i := 0; i < length; i++ { math.Pow(2, 100) }
//
//go:noinline
func burn(length int) float64 {
	var acc float64
	for i := 0; i < length; i++ {
		acc += math.Pow(2, 100)
	}
	return acc
}

func PostStress(c *gin.Context) {
	var req StressRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}

	// AES-GCM 프리앰블 (리버싱 재현). 산출물은 부하 자체엔 쓰이지 않는다.
	if _, err := aesGCMPreamble([]byte(req.RequestID + req.UUID)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "preamble failed"})
		return
	}

	// 고정 4개 goroutine 이 각각 length 회 반복 (2025: runtime.newproc 4회).
	const workers = 4
	var wg sync.WaitGroup
	sink := make([]float64, workers)
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			sink[idx] = burn(req.Length)
		}(w)
	}
	wg.Wait()

	c.JSON(http.StatusCreated, gin.H{
		"requestid": req.RequestID,
		"uuid":      req.UUID,
		"length":    req.Length,
	})
}

func Healthcheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}
