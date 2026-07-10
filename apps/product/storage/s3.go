package storage

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"time"

	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// Uploader — product 이미지 업로드용 S3 클라이언트 래퍼.
// env: S3_BUCKET (필수), AWS_REGION (기본 ap-northeast-2).
// 자격증명은 SDK 기본 체인(IRSA/노드 IAM 롤/환경변수)으로 해결한다.
type Uploader struct {
	client *s3.Client
	bucket string
}

func New(ctx context.Context) (*Uploader, error) {
	bucket := os.Getenv("S3_BUCKET")
	if bucket == "" {
		return nil, fmt.Errorf("S3_BUCKET not set")
	}
	region := os.Getenv("AWS_REGION")
	if region == "" {
		region = "ap-northeast-2"
	}

	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(region))
	if err != nil {
		return nil, err
	}
	return &Uploader{client: s3.NewFromConfig(cfg), bucket: bucket}, nil
}

// Put — 오브젝트를 S3 에 올리고 저장된 object key 를 반환한다.
// image_path 컬럼에는 이 key 를 저장하고, 다운로드는 인프라가 라우팅하는
// <endpoint>/images/<key> 경로로 제공된다(SPEC).
func (u *Uploader) Put(ctx context.Context, key string, body []byte, contentType string) (string, error) {
	cctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	_, err := u.client.PutObject(cctx, &s3.PutObjectInput{
		Bucket:      &u.bucket,
		Key:         &key,
		Body:        bytes.NewReader(body),
		ContentType: &contentType,
	})
	if err != nil {
		return "", err
	}
	return key, nil
}
