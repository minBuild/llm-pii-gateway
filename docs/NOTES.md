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
- [x] `turn_off_message_logging` 무유출 — 무도커 하니스로 라이브 litellm 로그에 원문 PII(전화/이메일/RRN) 없음 확인. (`store_prompts_in_spend_logs`=false; postgres spend 테이블 grep 은 로컬 도커 단계.)

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
- 2026-07-23 Phase 5: 감사 로거(`kpii.audit` JSONL, 원문/위치 없음) + Prometheus 메트릭(`kpii_*`, prometheus_client 옵션, `KPII_METRICS_PORT` 로 노출). 무유출: 컴포넌트 테스트(test_no_leak) + 무도커 하니스로 **라이브 litellm 로그 grep(원문 없음 확인)**. guardrail 에서 지연 측정(scan_latency_ms). audit `ner_degraded` 플래그는 아직 미스레드(근사값) — 백로그. operations/onboarding 문서 작성.
- 2026-07-23 B(탐지 품질): `tests/util/eval.py`(엔티티별 정밀도/재현율 측정 하니스) 추가. 하드 코퍼스 측정으로 **실제 미탐 2건 발견·수정** — (1) PHONE recall 0.43: 국제표기(+82 10-…)·괄호 지역번호((02)…) → `_MOBILE`/`_LANDLINE` 보강; (2) CREDENTIAL recall 0.67: Google API key(AIza…) → 패턴 추가. **최종 9개 엔티티 precision/recall 1.0, FP 0, 회귀 없음.** 엣지 케이스는 gen.positives 로 회귀 방지.
- 2026-07-23 B(탐지 품질, 카드): 실측으로 **CARD 가 15/16자리만 탐지되고 13/14/19자리는 전부 미탐**임을 확인(eval 의 CARD 1.0 은 15/16만 재던 것). 정규식을 "구분자 허용 13~19자리 **후보** + 코드에서 길이∈{15,16,19}+Luhn **확정**"으로 교체 → **19자리(Maestro/UnionPay, 연속·4-4-4-4-3) 탐지**. 13·14자리는 RRN(13)·ISBN-13 과 충돌하므로 길이셋에서 **의도적 제외**(문서화). RRN13 은 여전히 RRN(merge 는 동일 스팬에서 append 순서상 RRN 우선). eval 9엔티티 precision/recall 1.0·FP 0 유지, 유닛 **96 passed**. (남은 후보: NER lg 모델 정확도, 무하이픈 계좌 — 재현율↔정밀도 트레이드오프라 신중히.)
- 2026-07-24 적대적 회피 방어(THREAT_MODEL R1): 입력 정규화 `kpii/normalize.py`(NFKC + 제로폭/BIDI/소프트하이픈 제거) 추가 후 `openai_gateway._iter_scan_fields` 에 배선 — **정규화된 문자열로 탐지·마스킹·전달을 일관되게** 해 스팬 정합성 보장(정규화 후 마스킹하므로 원문 오프셋 어긋남 없음). 적대적 측정 하니스 `tests/util/adversarial.py`: 회피 6벡터 **raw 전부 미탐(뚫림)** 확인 → 전각·원형숫자·제로폭·소프트하이픈 4벡터는 정규화로 **12/12 복구**, 공백분리·한글표기("공일공")는 **잔여**(정밀도 리스크로 미대응, `tests/unit/test_normalize.py` 로 고정). eval 9엔티티 1.0/FP0 유지, 유닛 **106 passed**. THREAT_MODEL I1/R1 갱신(R1 높음→중간).
- 2026-07-24 프롬프트 인젝션 휴리스틱(THREAT_MODEL R2): `kpii/injection.py` — 카테고리별 (패턴,가중치) 점수화(OVERRIDE·EXFIL·ROLE·SUPPRESS·ENCODING·DELIM, 한/영), `normalize` 전처리 재사용(전각/제로폭 위장 무력화). 점수 임계는 정책이 결정. `Policy.injection`(enabled/action/threshold) 추가, `openai_gateway._finalize`에 배선(action=block 시 `PROMPT_INJECTION` 마커로 block_entities 합류, log_only는 관측만), guardrail은 인젝션 단독 차단 시 `[injection_blocked]` 마커, audit/metrics에 인젝션 필드 추가(카테고리/점수만, 원문 없음). 기본 정책 `log_only`(휴리스틱 FP 피해 최소화 — 이 판단 자체가 설계 포인트), with-ner은 `block` 데모. 벤치 `tests/util/injection_eval.py` **재현율 0.93/정밀도 0.93**(양성14·음성12) — 남은 FN=base64 스머글링(단독 약신호), FP=인젝션 문구 인용 소설(use-vs-mention). 둘 다 교과서적 난제라 과적합 대신 R2 잔여로 문서화. 유닛 **117 passed**, PII eval 1.0 회귀 없음. README를 능력(걸러내는 것)+한계 중심으로 재작성(Phase 트래커 제거), THREAT_MODEL R2 '부분완화 완료'로 갱신.
- 2026-07-24 잔여 리스크 정리(THREAT_MODEL R3~R6): **R3** 관측(감사/메트릭)을 try/except로 격리 — sink 실패가 차단/마스킹 결정을 무력화하지 못하게(‘보안 결정은 관측 성공에 의존하지 않는다’). scan 엔진 실패 시 `on_internal_error=allow`는 설계상 fail-open 유지(문서화). **R4** `max_scan_chars` 정책 가드(기본 0=off, 초과 시 413 `[oversized_input]` 차단) — 정규식은 이미 선형이라 ReDoS는 비실질, 크기 무한만 대응. **R5** multimodal `input_text`(Responses API) 파트 미스캔 갭 발견·수정(`_iter_scan_fields`). **R6** 스트리밍 복원을 `choice.index` 별 독립 `StreamRestorer`로 → n>1 복원. 신규 `tests/unit/test_hardening.py`(R4/R5/R6 오프라인 6) + `test_guardrail.py`에 R3/인젝션차단/오버사이즈 마커 3건(litellm 설치돼 있어 실제 실행·통과). 유닛 **126 passed**, PII 1.0·인젝션 0.93 회귀 없음. THREAT_MODEL R3~R6·D3·E1·I6 갱신.

## Presidio(NER) 검증 현황 (Phase 4 / A)
검증 완료(spaCy 3.8.13 + ko_core_news_sm 3.8.0 + presidio-analyzer, in-process):
- [x] NER 라벨셋: **DT/LC/OG/PS/QT/TI** (sm/md/lg 동일). `presidio/nlp_conf.yaml` 주석에 기록.
- [x] `nlp_conf` 매핑 실제 적용: AnalyzerEngine 로 김민수→PERSON(0.85), 서울시→LOCATION(0.85) 확인 → `tests/unit/test_presidio_live.py`(모델 있으면 실행, 없으면 skip).
- [x] 결과 필드(entity_type/start/end/score)가 `PresidioClient` 파싱과 일치.

남은 확인(도커 사이드카 실행 시):
- [ ] REST `/analyze` HTTP 래퍼 포맷·포트(3000?)·이미지 NLP 설정 로드 방식(이미지 버전별).
- [ ] 운영 정확도(lg 모델로 교체) · NER on/off p95 지연(각 20회) 측정(DESIGN Phase 4 item 6).
- 로컬 NER E2E: `docker compose -f docker-compose.yml -f docker-compose.test.yml --profile ner up -d --build` + guardrail 정책 `with-ner.yaml` + `KPII_NER_E2E=1 pytest -m integration`.
