# 구현 노트 — LiteLLM 검증·결정 기록 (DESIGN §9)

## LiteLLM 버전
- Dockerfile: `ghcr.io/berriai/litellm:v1.93.0-stable`.
- 로컬 dev venv 에 `pip install litellm` → **1.93.0** 설치·검증(가드레일 훅 API 확인용).
- 빌드 시 ghcr 에 `v1.93.0-stable` 태그 존재 확인. 없으면 `v1.93.0` 또는 최근 `-stable`.

## LiteLLM API 검증 (§9-1)
**검증 완료** — litellm 1.93.0 실제 소스 introspection:
- `CustomGuardrail` 훅:
  - `async_pre_call_hook(self, user_api_key_dict, cache, data, call_type) -> Exception|str|dict|None`
  - `async_post_call_success_hook(self, data, user_api_key_dict, response)`
  - `async_post_call_streaming_iterator_hook(self, user_api_key_dict, response, request_data) -> AsyncGenerator`
  - `__init__(self, guardrail_name=None, ..., default_on=False, **kwargs)` — 커스텀 kwargs 허용.
- 차단: `litellm.proxy._types.ProxyException(message, type, param, code, openai_code=...)`.
  오프라인 훅 호출에서 `openai_code="pii_blocked"`, `type="invalid_request_error"`, `code="400"`, 원문 미유출 확인.

**라이브 프록시에서 최종 확인 필요** (이 환경은 compose 미가용 → 오프라인 훅 테스트로 대체):
- [ ] config `guardrails` 스키마(guardrail_name / litellm_params.guardrail / mode / default_on / policy_path)가 1.93.0 에서 그대로 로드되는지.
- [ ] `data["metadata"]["kpii_mapping"]` 가 pre_call → post/streaming 훅까지 유지되는지 (Phase 3). 안 되면 litellm_call_id 키 모듈-레벨 dict + TTL 폴백 (DESIGN §6.3).
- [ ] ProxyException 이 §5.4 형태(`{"error": {..., "code": "pii_blocked"}}`)로 직렬화되는지.
- [ ] `turn_off_message_logging` / `store_prompts_in_spend_logs` 무유출 (Phase 5 테스트로 강제).

## 환경
- 로컬 dev: Python 3.14 venv. 코어 단위테스트 오프라인 통과(63 passed). litellm/fastapi 설치 시 guardrail·fake_upstream 테스트도 실행되고, 미설치면 `importorskip` 로 skip.
- Docker 29.x 이나 **compose 플러그인/v1 미설치** → `make test-integration`(프록시 E2E)은 compose 가능한 로컬에서 실행. 통합테스트는 `@pytest.mark.integration`.

## 결정 로그
- 2026-07-22 Phase 1: 부록 B 정규식 오탐 감소 조정 — DRIVER_LICENSE 문맥(면허/운전) 필수, BANK_ACCOUNT 키워드에서 흔한 일반어 은행명(우리/하나/기업 등) 제외.
- 2026-07-22 Phase 2: `custom_guardrails/` 를 레포 루트로 이동(원래 `litellm/custom_guardrails/`). 이유: 로컬에서 `custom_guardrails.kpii_guardrail` import 가 도커(/app 기준)와 동일하게 되도록. `litellm/` 엔 config.yaml 만 남김(pip `litellm` 패키지를 shadow 하지 않음 — 검증함).
- 2026-07-22 Phase 2: 탐지/마스킹 로직은 `kpii/openai_gateway.py`(litellm 무의존), `custom_guardrails/kpii_guardrail.py` 는 얇은 어댑터. 차단은 ProxyException.
- 2026-07-22 Phase 2: litellm 은 proxy extra(`pip install -e ".[proxy]"`)로 분리 — 코어 단위테스트는 litellm 없이 통과.
- 2026-07-22 Phase 3: 응답 복원 — `async_post_call_success_hook`(비스트리밍) + `async_post_call_streaming_iterator_hook`(스트리밍, StreamRestorer). 매핑 없으면 버퍼링 없이 통과. `metadata.kpii_mapping` 이 pre_call→post 훅까지 유지되는지는 라이브 프록시 확인 항목(상단 체크리스트). 스트리밍은 단일 choice(n=1) 가정.
