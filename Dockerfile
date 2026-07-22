# LiteLLM 프록시 + kpii 코어/가드레일 포함 이미지 (DESIGN §6.5)
# NOTE: main-stable 은 rolling 태그. 재현성을 위해 특정 vX.Y.Z-stable 로 고정 예정 (docs/NOTES.md).
FROM ghcr.io/berriai/litellm:main-stable

COPY kpii /app/kpii
COPY litellm/custom_guardrails /app/custom_guardrails
COPY policies /app/policies

ENV PYTHONPATH="/app:${PYTHONPATH}"

# kpii 의존성 (LiteLLM 이미지에 대개 포함되지만 명시). Phase 4에서 httpx 추가.
RUN pip install --no-cache-dir "pyyaml>=6"
