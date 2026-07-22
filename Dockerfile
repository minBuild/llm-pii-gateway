# LiteLLM 프록시 + kpii 코어/가드레일 포함 이미지 (DESIGN §6.5)
# 로컬 검증한 pip litellm 버전(1.93.0)에 맞춰 stable 태그 고정.
# NOTE: 빌드 시 ghcr 에 v1.93.0-stable 태그 존재 확인. 없으면 v1.93.0 또는 최근 -stable 사용.
FROM ghcr.io/berriai/litellm:v1.93.0-stable

COPY kpii /app/kpii
COPY custom_guardrails /app/custom_guardrails
COPY policies /app/policies

ENV PYTHONPATH="/app:${PYTHONPATH}"

# kpii 의존성 (LiteLLM 이미지에 대개 포함되지만 명시). Phase 4에서 httpx 추가.
RUN pip install --no-cache-dir "pyyaml>=6"
