# llm-pii-gateway

개인 연구 프로젝트. **한국어 LLM 보안 게이트웨이 (LiteLLM Proxy 기반).**
OpenAI 호환 요청이 외부 LLM API(OpenAI·Anthropic 등)로 나가기 전에 **개인정보(PII)·크리덴셜을
탐지해 가역 마스킹/차단**하고, **프롬프트 인젝션을 플래깅**하며, 응답에서 원문을 복원한다.

- 설계: [DESIGN.md](DESIGN.md) · 위협 모델: [THREAT_MODEL.md](THREAT_MODEL.md) · 구현 노트: [docs/NOTES.md](docs/NOTES.md)

## 걸러내는 것 (What it catches)

### 1) 개인정보·민감정보 — L1 정규식 + 체크섬 (인프로세스, 항상 동작)

| 종류 | 탐지 방식 | 기본 조치 |
|---|---|---|
| 주민등록번호 (RRN) | 생년월일 유효성 게이트 (+체크섬은 신뢰도) | **차단** |
| 신용카드 (CARD) | 15·16·19자리 + Luhn 체크섬 | 마스킹 |
| 전화번호 (PHONE) | 휴대폰·유선 (국제표기 `+82`·괄호 지역번호 `(02)` 포함) | 마스킹 |
| 이메일 (EMAIL) | 정규식 | 마스킹 |
| 여권번호 (PASSPORT) | 형식 + 문맥어(`여권`) | 마스킹 |
| 운전면허 (DRIVER_LICENSE) | 형식 + 문맥어(`면허`/`운전`) | 마스킹 |
| 계좌번호 (BANK_ACCOUNT) | 형식 + 문맥어(`계좌`/`입금`…) | 마스킹 |
| 사업자등록번호 (BRN) | 체크섬 | 로그만 |
| 이름·주소 (PERSON/LOCATION) | **L2 Presidio 한국어 NER** (사이드카, 선택) | 마스킹 |

체크섬·문맥 게이트로 오탐을 줄인다(예: 12자리 주문번호·형식만 같은 숫자열은 미탐).
엔티티별 조치는 [`policies/default.yaml`](policies/default.yaml)에서 정책으로 조정.

### 2) 크리덴셜 (CREDENTIAL, 기본 차단)

OpenAI `sk-…`, AWS `AKIA…`, GitHub `ghp_…`, Google `AIza…`, Slack `xox[baprs]-…`, PEM 개인키.

### 3) 적대적 회피 방어 — 입력 정규화 전처리

전각(`０１０`)·원형숫자(`①`)·제로폭·소프트하이픈·BIDI 제어 문자로 탐지를 **우회하려는 시도**를
NFKC + 보이지 않는 문자 제거로 접어, 위 탐지가 뚫리지 않게 한다. (측정: `tests/util/adversarial.py`)

### 4) 프롬프트 인젝션 — 휴리스틱 플래깅 (기본 `log_only`)

한/영 표현군을 카테고리로 점수화: 지시 무효화(OVERRIDE), 시스템 프롬프트 탈취(EXFIL),
역할 탈취·탈옥(ROLE), 거절 억제(SUPPRESS), 인코딩 스머글링(ENCODING), 채팅 제어토큰(DELIM).
기본은 관측(`log_only`), 정책으로 `block` 전환 가능. (측정: `tests/util/injection_eval.py`)

## 정직한 한계 (What it does NOT catch)

능력만큼 한계도 명시한다 — 보안 게이트웨이는 방어 경계를 아는 것이 핵심이다.

- **프롬프트 인젝션은 휴리스틱**이다. 의역·신규 표현, 간접 인젝션(RAG/tool 출력), 인용/설명뿐인
  정상문(use-vs-mention), KO/EN 외 언어는 못 잡는다. 벤치마크 재현율/정밀도 ≈ **0.93/0.93**.
- **이름·주소(NER)** 는 선택적 사이드카이며 모델 정확도(sm)에 한계가 있다.
- **무하이픈 계좌·13/14자리 카드** 등은 오탐 폭증을 피하려 **의도적으로** 탐지하지 않는다.
- 낱자 공백 분리(`0 1 0 …`)·한글 낱말 표기(`공일공`) 같은 회피는 정규화로도 못 막는다.

전체 공격면·완화·잔여 리스크 등록부는 [THREAT_MODEL.md](THREAT_MODEL.md) 참조.

## 동작 방식

```
요청 → [정규화] → L1 탐지(+선택 L2 NER) → 인젝션 점검
     → 차단 | 가역 마스킹([PHONE_1]) → 업스트림 LLM → 응답에서 원문 복원 → 클라이언트
```

- **가역 마스킹**: `홍길동 → [PERSON_1]` 로 치환해 업스트림 전송, 응답에서 복원. 매핑은 **요청 스코프
  인메모리만**(저장·로그 금지).
- **차단은 최소**: 주민등록번호·크리덴셜 등 최고 위험만 차단, 나머지는 마스킹.
- **로그 무유출**: 감사 로그(JSONL)·메트릭에 PII 원문을 남기지 않는다(테스트로 강제).
- **안전한 실패**: 필터 내부 오류·NER 장애 시 정책에 따라 fail-closed(차단) 가능.

## 빠른 시작

```bash
make venv         # .venv 생성 + 개발 의존성 설치
make test-unit    # 오프라인 단위테스트 (litellm/fastapi 설치 시 guardrail·복원·E2E 하니스도 실행)
```

게이트웨이 기동(도커):

```bash
cp .env.example .env    # 업스트림 키 등 채우기
make build && make up
make smoke              # GET /health/liveliness
```

## 구조

| 경로 | 설명 |
|---|---|
| `kpii/` | 탐지·마스킹 코어 (LiteLLM 무의존, 순수 파이썬) — `normalize.py`(정규화), `injection.py`(인젝션) 포함 |
| `custom_guardrails/` | LiteLLM guardrail 어댑터 (얇은 어댑터) |
| `litellm/` | LiteLLM 프록시 설정 (config.yaml) |
| `policies/` | 정책 yaml (`default.yaml`, `with-ner.yaml`) |
| `presidio/` | 한국어 NER 사이드카 (L2) |
| `tests/` | 단위(오프라인)/통합(도커) 테스트 + 측정 하니스(eval·adversarial·injection_eval) |
| `docs/` | 구현 노트·운영/사용 문서 |
| `DESIGN.md` · `THREAT_MODEL.md` | 설계 / 위협 모델(STRIDE × OWASP LLM Top 10) |

## 벤치마크 & 향후

- **필터 오버헤드·처리량 벤치**: [`bench/`](bench/) — 필터가 요청당 얹는 지연은 최악(heavy)에도
  p99 ~52µs(LLM 호출 대비 무시 수준). 처리량은 Python(GIL)이 스레드 확장 없이 ~21k ops/s로 평평한
  반면, JVM 플랫폼 스레드는 18코어에서 ~362k ops/s(~17×)로 선형 확장 — "Python 먼저, 처리량이
  중요해지면 JVM 포트" 방향을 수치로 뒷받침(DESIGN §10.1).
- 향후: 전체 사양 JVM(가상 스레드) 포트 + 실게이트웨이 부하시험(업스트림 I/O 동시성).
