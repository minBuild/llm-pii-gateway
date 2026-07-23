# 운영 가이드 (operations)

## 기동 / 중지
- 기동: `make build && make up` (litellm + postgres). 헬스: `make smoke`(GET /health/liveliness).
- 로그: `make logs`. 중지: `make down`.
- 통합 스택(fake upstream 포함): `make up-test` → `make test-integration` → `make down-test`.
- NER 스택: `docker compose -f docker-compose.yml -f docker-compose.test.yml --profile ner up -d --build` + guardrail 정책을 `with-ner.yaml` 로.

## 정책 변경·반영
- 정책은 `policies/*.yaml`(§4.3). guardrail 이 **시작 시 1회 로드**하므로 변경 후 **프록시 재기동** 필요.
- 어느 정책을 쓸지: `litellm/config.yaml` 의 `guardrails.litellm_params.policy_path`(또는 `KPII_POLICY_PATH` 환경변수).
- 조정 항목: 엔티티별 `action`(block/mask/log_only/off), `on_internal_error`, `ner.*`.
- ⚠️ litellm 은 guardrail 모듈을 **config 파일 디렉터리 기준**으로 로드한다 → `config.yaml` 과 `custom_guardrails/` 는 같은 디렉터리에 있어야 함(도커 `/app`). (docs/NOTES.md 참고)

## 키 발급 (LiteLLM 가상 키)
```bash
curl -X POST http://<gateway>:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'content-type: application/json' -d '{"key_alias":"team-x"}'
```
클라이언트에는 **가상 키**를 배포한다(마스터 키 직접 노출 금지). 용도별 비용 추적·레이트리밋이 가상 키 단위로 붙는다.

## 로그 / 메트릭
- **감사 로그**: `kpii.audit` 로거가 §7.1 JSONL 을 stdout 으로 출력(수집은 표준 로깅 파이프라인에 위임). **원문 없음** — 엔티티 타입/카운트/액션/지연만.
- **메트릭**: `KPII_METRICS_PORT` 설정 시 그 포트로 Prometheus 노출. `curl http://localhost:$KPII_METRICS_PORT`:
  - `kpii_detections_total{entity,action}` / `kpii_blocked_requests_total` / `kpii_scan_latency_seconds` / `kpii_ner_failures_total`
- **무유출**: 로그·메트릭에 PII 원문이 없어야 한다. `tests/unit/test_no_leak.py`(컴포넌트) + 라이브 로그 grep 으로 강제.

## Presidio(NER) 장애 대응
- `ner.on_failure: degrade` → NER 사이드카가 죽어도 L1(정규식/체크섬)만으로 계속. 게이트웨이 200 유지.
- `ner.on_failure: block` → NER 불가 시 **503 차단**(안전 우선).
- `kpii_ner_failures_total` 로 실패 관측. presidio-analyzer 는 모델 로딩에 메모리가 필요(≥2G 권장).

## 흔한 이슈
- **차단(400)**: 응답 `error.message` 가 `[pii_blocked]` + 엔티티 타입으로 시작. 사용자에게 해당 값 제거를 안내.
- **푸시 인증(개발)**: 이 레포는 로컬 `credential.helper`(gh)로 개인 계정 인증. 전역(회사) 설정은 건드리지 않음.
