# 구현 노트 — LiteLLM 검증·결정 기록 (DESIGN §9)

## LiteLLM 버전
- 현재 `Dockerfile`: `ghcr.io/berriai/litellm:main-stable` (rolling 태그).
- **잔여 작업(Phase 0)**: 재현성을 위해 특정 `vX.Y.Z-stable` 로 고정할 것. 이 세션에서는
  최신 stable 버전 번호를 네트워크로 확정하지 못해 임시로 rolling 태그를 사용 중이다.
  `ghcr.io/berriai/litellm` 패키지 또는 GitHub releases 에서 확인 후 고정한다.

## 구현 전 실제 버전 소스에서 확인할 것 (§9-1, 추측 금지)
- [ ] 이미지 ENTRYPOINT/CMD — compose `command: --config /app/config.yaml --port 4000` 가 맞는지.
- [ ] guardrail 훅 시그니처: `async_pre_call_hook` / `async_post_call_success_hook` /
      `async_post_call_streaming_iterator_hook` (`litellm/integrations/custom_guardrail.py`).
- [ ] `data["metadata"]` 가 pre_call → post/streaming 훅까지 유지되는지(매핑 전달 경로).
      안 되면 `litellm_call_id` 키 모듈-레벨 dict + TTL 폴백 (DESIGN §6.3).
- [ ] guardrail `mode` 표기와 post 훅 활성화 방식, 요청별 guardrail 해제 가능 여부
      (가능하면 반드시 비활성화 — 사용자가 필터를 못 끄게).
- [ ] `turn_off_message_logging` / `store_prompts_in_spend_logs` 가 실제로 콜백·spend 로그에
      원문을 남기지 않는지 → Phase 5 무유출 테스트로 강제.

## 환경 (이 저장소 기준)
- 로컬 개발: Python 3.14 venv(`.venv`), pytest 9.x. 코어 타깃은 3.11+.
- Docker 29.x. Phase 1 단위테스트는 `make test-unit` 로 오프라인 통과 확인됨(51 passed).
- `make up` 헬스체크는 업스트림 키 + 이미지 pull 이 필요해 로컬에서 실행한다(이 세션 미실행).

## 결정 로그
- 2026-07-22 Phase 1: 부록 B 정규식을 오탐 감소 방향으로 조정 — DRIVER_LICENSE 는 체크섬이
  없어 12자리 숫자열과 충돌하므로 문맥 키워드(면허/운전) 필수로 변경. BANK_ACCOUNT 문맥
  키워드에서 흔한 일반어와 겹치는 은행명(우리/하나/기업 등)은 제외.
- (양식) LiteLLM 동작이 문서와 다르면 여기에 "무엇을 시도했고 왜 우회했는지" 기록.
