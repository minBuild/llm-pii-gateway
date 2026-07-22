# llm-pii-gateway

개인 연구 프로젝트. **LiteLLM Proxy 기반 한국어 개인정보(PII) 필터링 게이트웨이.**
OpenAI 호환 요청이 외부 LLM API(OpenAI·Anthropic 등)로 나가기 전에 PII를 탐지해
가역 마스킹/차단하고, 응답에서 원문을 복원한다. 상세 설계는 [DESIGN.md](DESIGN.md).

## 상태 (Phase)

- [x] **Phase 1** — kpii 코어: L1 정규식·체크섬 탐지 + 가역 마스킹 + 스트리밍 복원.
- [~] **Phase 0** — 스캐폴딩/LiteLLM 골격: 파일 작성 완료. `make up` 헬스체크는 로컬(키·이미지 필요)에서 실행.
- [~] **Phase 2** — 요청 방향 마스킹/차단: guardrail 어댑터 + 요청 스캔 코어 + fake upstream. 오프라인 단위테스트 통과(litellm/fastapi 검증 포함). 프록시 E2E 통합테스트는 로컬 도커(`make up-test && make test-integration`).
- [~] **Phase 3** — 응답 복원(비스트리밍·스트리밍): post-call 훅 + StreamRestorer 복원. 오프라인 검증. 프록시 E2E는 로컬 도커.
- [ ] **Phase 4** — Presidio 한국어 NER 사이드카 (이름·주소)
- [ ] **Phase 5** — 감사 로그·메트릭·무유출 테스트
- 향후 — JVM(Kotlin/Java 가상 스레드) 포트로 처리량·tail latency 벤치마크 (DESIGN §10.1)

## 빠른 시작

### 단위 테스트 (오프라인, 도커 불필요)

```bash
make venv         # .venv 생성 + 개발 의존성 설치
make test-unit    # 73 passed (litellm/fastapi 있으면 guardrail·fake-upstream·복원 테스트도 실행)
```

### 게이트웨이 기동 (도커)

```bash
cp .env.example .env    # 업스트림 키 등 채우기
make build && make up
make smoke              # GET /health/liveliness
```

## 구조

| 경로 | 설명 |
|---|---|
| `kpii/` | 탐지·마스킹 코어 (LiteLLM 무의존, 순수 파이썬) |
| `custom_guardrails/` | LiteLLM guardrail 어댑터 (얇은 어댑터, Phase 2) |
| `litellm/` | LiteLLM 프록시 설정 (config.yaml) |
| `policies/` | PII 정책 yaml (`default.yaml`) |
| `tests/` | 단위(오프라인) / 통합(도커) 테스트 + 합성 코퍼스 |
| `presidio/` | 한국어 NER 사이드카 (Phase 4) |
| `docs/` | 구현 노트·운영/사용 문서 |

## 설계 요약

- **탐지 2계층**: L1(정규식+체크섬, 인프로세스, 항상) + L2(Presidio NER, 사이드카, 선택).
- **가역 마스킹**: `홍길동 → [PERSON_1]` 로 치환해 업스트림 전송, 응답에서 복원. 매핑은 요청 스코프 인메모리만(저장·로그 금지).
- **차단은 최소**: 주민등록번호·크리덴셜 등 최고 위험만 BLOCK, 나머지는 MASK.
- **로그 무유출**: 감사 로그·메트릭에 PII 원문을 남기지 않음(테스트로 강제, Phase 5).
