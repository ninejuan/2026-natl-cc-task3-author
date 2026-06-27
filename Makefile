APPS        := user product stress
BUILD_DIR   := build
TASK3_PROVIDED := ../task3/provided

GOOS   := linux
GOARCH := amd64

.PHONY: build publish clean loadgen grade

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

loadgen:
	python3 loadgen/main.py

grade:
	python3 grader/main.py

clean:
	rm -rf $(BUILD_DIR)/*
