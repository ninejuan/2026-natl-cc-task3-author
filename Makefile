APPS        := user product stress
BUILD_DIR   := build
TASK3_PROVIDED := ../task3/provided

GOOS   := linux
GOARCH := amd64

# 부하/채점 파라미터 (환경변수로 덮어쓰기 가능)
#   make loadgen ENDPOINT=https://xxx STUDENT_ID=12345 DURATION=1800 MULTIPLIER=1.5
STUDENT_ID  ?= 00000
ENDPOINT    ?=
DURATION    ?= 300
MULTIPLIER  ?= 1.0
CONCURRENCY ?= 64
PYTHON      ?= python3

# seed S3 업로드 파라미터
S3_BUCKET   ?=
AWS_REGION  ?= ap-northeast-2

.PHONY: build publish clean deps loadgen nodes grade seed-s3

build:
	@mkdir -p $(BUILD_DIR)
	@for app in $(APPS); do \
		echo "building $$app ..."; \
		( cd apps/$$app && GOOS=$(GOOS) GOARCH=$(GOARCH) CGO_ENABLED=0 go build -o ../../$(BUILD_DIR)/$$app . ); \
	done
	@echo "built: $(APPS) -> $(BUILD_DIR)/"

publish: build
	@for app in $(APPS); do cp $(BUILD_DIR)/$$app $(TASK3_PROVIDED)/$$app; done
	@echo "published binaries -> $(TASK3_PROVIDED)/"

deps:
	$(PYTHON) -m pip install -r requirements.txt

# 트래픽 주입. ENDPOINT 필수.
loadgen:
	@test -n "$(ENDPOINT)" || { echo "error: ENDPOINT 를 지정하세요 (예: make loadgen ENDPOINT=https://xxx STUDENT_ID=12345)"; exit 1; }
	$(PYTHON) loadgen/main.py \
		--endpoint "$(ENDPOINT)" --student-id "$(STUDENT_ID)" \
		--duration $(DURATION) --multiplier $(MULTIPLIER) --concurrency $(CONCURRENCY)

# cost ratio 용 노드 수 샘플러. loadgen 과 병렬 실행 (별도 터미널 또는 &).
nodes:
	$(PYTHON) loadgen/nodes.py --student-id "$(STUDENT_ID)" --duration $(DURATION)

# 채점. loadgen/nodes 결과 로그를 읽어 results_<비번호>.log 생성.
grade:
	$(PYTHON) grader/main.py --student-id "$(STUDENT_ID)"

# ---- seed 데이터 -----------------------------------------------------------
# 앱별로 커밋된 자료: apps/user/seed/load_user.sql, apps/product/seed/load_product.sql,
# apps/product/seed/images/. RDS 반영은 mysql < ...load_*.sql, 이미지는 아래로 S3 업로드.
# 파일명이 곧 object key(=image_path=/images/<key>)라 sync 만 하면 된다.
seed-s3:
	@test -n "$(S3_BUCKET)" || { echo "error: S3_BUCKET 를 지정하세요 (예: make seed-s3 S3_BUCKET=my-bucket)"; exit 1; }
	aws s3 sync apps/product/seed/images/ s3://$(S3_BUCKET)/ --exclude '.gitkeep' --region $(AWS_REGION)

clean:
	find $(BUILD_DIR) -type f ! -name '.gitkeep' -delete
