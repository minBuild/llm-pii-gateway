# 사용법 (onboarding)

이 게이트웨이는 **OpenAI 호환**입니다. 기존 코드에서 **base URL 과 API 키만** 게이트웨이로
바꾸면 됩니다. 요청 속 개인정보(PII)는 자동으로 마스킹/차단되고, 응답에선 원문이 복원됩니다.

## base URL 바꾸기

### Python (openai SDK)
```python
from openai import OpenAI
client = OpenAI(base_url="http://<gateway>:4000/v1", api_key="<발급받은 가상 키>")
client.chat.completions.create(model="claude-sonnet-5", messages=[{"role": "user", "content": "..."}])
```

### JavaScript
```js
import OpenAI from "openai";
const client = new OpenAI({ baseURL: "http://<gateway>:4000/v1", apiKey: "<키>" });
```

### curl
```bash
curl http://<gateway>:4000/v1/chat/completions \
  -H "Authorization: Bearer <키>" -H 'content-type: application/json' \
  -d '{"model":"claude-sonnet-5","messages":[{"role":"user","content":"안녕"}]}'
```

## 키 발급
운영자에게 용도(`key_alias`)를 알려주고 **가상 키**를 발급받으세요. 마스터 키는 사용하지 않습니다.

## 어떻게 동작하나
- 전화·이메일·카드번호 등은 `[PHONE_1]` 같은 플레이스홀더로 치환되어 외부 LLM 에 전달되고, **응답에서 원문으로 복원**됩니다(스트리밍 포함). 즉 여러분 코드는 평소처럼 원문 응답을 받습니다.
- 이름·주소는 NER(L2) 활성 시 마스킹됩니다.
- 로그에는 원문이 남지 않습니다.

## 차단(400 pii_blocked) 되었을 때
주민등록번호·API 키 같은 최고위험 정보는 마스킹이 아니라 **차단**됩니다:
```json
{"error": {"message": "[pii_blocked] 요청에 차단 대상 민감정보가 포함되어 있습니다: RRN(주민등록번호)...",
           "type": "invalid_request_error", "param": null, "code": "400"}}
```
→ 해당 값을 제거하고 다시 요청하세요. (기계 판별은 메시지의 `pii_blocked` 마커로.)
