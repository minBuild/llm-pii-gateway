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

**라이브 E2E 검증 완료** — compose 없이 로컬 하니스로 실행(litellm[proxy] 프록시 + uvicorn fake upstream). 통합테스트 **8/8 통과**. 발견/해결:
- [x] config `guardrails` 스키마 1.93.0 로드 OK. **단 mode 는 리스트여야 함**: `[pre_call, post_call]`. pre 만 주면 응답 복원(post) 훅이 `should_run_guardrail(post_call)` 게이팅으로 실행되지 않음 (custom_guardrail.py L618-619).
- [x] `metadata.kpii_mapping` 가 pre_call → post 훅까지 유지됨(응답 복원이 E2E로 동작 = 확인).
- [x] ProxyException 직렬화: `{"error": {message, type, param, code}}`. **openai_code 는 본문에 노출 안 됨**, `code` 엔 HTTP 상태("400"). → PII 차단 식별 마커 `[pii_blocked]` 를 message 에 포함.
- [x] guardrail 모듈 로드: litellm `get_instance_fn` 은 **config 파일 디렉터리 기준**으로 `custom_guardrails/kpii_guardrail.py` 로드(PYTHONPATH 아님). config 와 custom_guardrails/ 를 같은 디렉터리에 둘 것(도커 /app, 로컬은 repo 루트 config).
- [ ] `turn_off_message_logging` / `store_prompts_in_spend_logs` 무유출 — Phase 5 무유출 테스트로 강제(미검증).

**무도커 로컬 E2E 방법**(compose 없이): `pip install -e ".[proxy]"` → fake upstream `uvicorn tests.fake_upstream.app:app --port 9000` → repo 루트에 config(mode:[pre_call,post_call], mock-model→127.0.0.1:9000, master_key) 두고 `litellm --config <repo>/config.yaml --port 4000` → `GATEWAY_URL=... FAKE_UPSTREAM_URL=... pytest -m integration`.

## 환경
- 로컬 dev: Python 3.14 venv. 코어 단위테스트 오프라인 통과(63 passed). litellm/fastapi 설치 시 guardrail·fake_upstream 테스트도 실행되고, 미설치면 `importorskip` 로 skip.
- Docker 29.x 이나 **compose 플러그인/v1 미설치** → `make test-integration`(프록시 E2E)은 compose 가능한 로컬에서 실행. 통합테스트는 `@pytest.mark.integration`.

## 결정 로그
- 2026-07-22 Phase 1: 부록 B 정규식 오탐 감소 조정 — DRIVER_LICENSE 문맥(면허/운전) 필수, BANK_ACCOUNT 키워드에서 흔한 일반어 은행명(우리/하나/기업 등) 제외.
- 2026-07-22 Phase 2: `custom_guardrails/` 를 레포 루트로 이동(원래 `litellm/custom_guardrails/`). 이유: 로컬에서 `custom_guardrails.kpii_guardrail` import 가 도커(/app 기준)와 동일하게 되도록. `litellm/` 엔 config.yaml 만 남김(pip `litellm` 패키지를 shadow 하지 않음 — 검증함).
- 2026-07-22 Phase 2: 탐지/마스킹 로직은 `kpii/openai_gateway.py`(litellm 무의존), `custom_guardrails/kpii_guardrail.py` 는 얇은 어댑터. 차단은 ProxyException.
- 2026-07-22 Phase 2: litellm 은 proxy extra(`pip install -e ".[proxy]"`)로 분리 — 코어 단위테스트는 litellm 없이 통과.
- 2026-07-22 Phase 3: 응답 복원 — `async_post_call_success_hook`(비스트리밍) + `async_post_call_streaming_iterator_hook`(스트리밍, StreamRestorer). 매핑 없으면 버퍼링 없이 통과. `metadata.kpii_mapping` 이 pre_call→post 훅까지 유지되는지는 라이브 프록시 확인 항목(상단 체크리스트). 스트리밍은 단일 choice(n=1) 가정.
- 2026-07-22 Phase 4: L2(NER) — 비동기 `PresidioClient`(HTTP `/analyze`) + `engine.scan_async` + `openai_gateway.process_request_async`(필드별 NER 동시 호출). guardrail 은 `policy.ner.enabled` 시 async 경로. NER 실패는 `NerUnavailable` → `on_failure=block`이면 ProxyException 503, `degrade`면 경고 후 L1만. 오프라인 12건(모킹) 통과. **실제 Presidio E2E는 이 환경 미실행**(모델이 무거움) — Phase 2/3와 달리 라이브 NER 미검증.

## Presidio 사이드카 — 로컬 확인 필요 (Phase 4)
- [ ] presidio-analyzer 이미지 태그 고정 + NLP 설정 파일 로드 경로/환경변수/포트(3000?) — 이미지 버전마다 다름.
- [ ] `ko_core_news_lg` 실제 NER 라벨셋(`python -c "import spacy; print(spacy.load('ko_core_news_lg').pipe_labels['ner'])"`) → `presidio/nlp_conf.yaml` PS/LC/OG 매핑 조정.
- [ ] `/analyze` 요청·응답 포맷이 `PresidioClient` 파싱과 일치하는지(문서 기준으로 구현함).
- [ ] NER on/off p95 지연 측정(각 20회) 기록(DESIGN Phase 4 item 6).
- 로컬 NER E2E: `docker compose -f docker-compose.yml -f docker-compose.test.yml --profile ner up -d --build` + guardrail 정책을 `with-ner.yaml` 로 + `KPII_NER_E2E=1 pytest -m integration`. (또는 무도커 하니스 + presidio 로컬 실행 + with-ner config.)
