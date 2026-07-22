VENV := .venv/bin

.PHONY: help venv build up down logs smoke test-unit test-integration fixtures lint

help: ## 사용 가능한 타깃 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

venv: ## 로컬 venv 생성 + 개발 의존성 설치
	python3 -m venv .venv && $(VENV)/pip install -q -U pip && $(VENV)/pip install -q -e ".[dev,ner]"

build: ## 도커 이미지 빌드
	docker compose build

up: ## 게이트웨이 + postgres 기동
	docker compose up -d

down: ## 중지 및 볼륨 정리
	docker compose down

logs: ## litellm 로그 팔로우
	docker compose logs -f litellm

smoke: ## 헬스체크 (기동 후)
	curl -fsS http://localhost:4000/health/liveliness && echo " OK"

test-unit: ## 오프라인 단위테스트 (도커 불필요)
	$(VENV)/python -m pytest tests/unit -q

test-integration: ## 통합테스트 (docker compose 필요, Phase 2+)
	$(VENV)/python -m pytest tests -m integration -q

fixtures: ## 합성 코퍼스 재생성
	$(VENV)/python -m tests.util.gen

lint: ## ruff 린트
	$(VENV)/ruff check kpii tests
