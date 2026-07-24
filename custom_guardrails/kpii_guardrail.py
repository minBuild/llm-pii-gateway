"""LiteLLM 커스텀 guardrail 어댑터 (DESIGN §6.3).

얇은 어댑터: 탐지/마스킹 판단은 kpii.openai_gateway 가, HTTP/예외 변환과 매핑 전달은 여기가.
훅 시그니처는 litellm 1.93.0 실제 소스에서 검증(docs/NOTES.md).

- Phase 2: async_pre_call_hook — 스캔·마스킹·차단·매핑 저장.
- Phase 3: async_post_call_success_hook / async_post_call_streaming_iterator_hook 에서 복원.
"""

from __future__ import annotations

import os
import time
from typing import Any

from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.proxy._types import ProxyException

from kpii import metrics
from kpii.audit import event_from_result, log_event
from kpii.masking import MaskingSession, StreamRestorer, restore
from kpii.openai_gateway import process_request, process_request_async
from kpii.policy import Policy
from kpii.types import NerUnavailable

_ENTITY_LABELS = {
    "RRN": "주민등록번호",
    "CREDENTIAL": "인증정보(키/토큰)",
    "CARD": "카드번호",
    "PHONE": "전화번호",
    "EMAIL": "이메일",
    "DRIVER_LICENSE": "운전면허번호",
    "PASSPORT": "여권번호",
    "BANK_ACCOUNT": "계좌번호",
    "BRN": "사업자등록번호",
    "PERSON": "이름",
    "LOCATION": "주소",
    "PROMPT_INJECTION": "프롬프트 인젝션 의심",
}
INJECTION_MARKER = "PROMPT_INJECTION"
MAPPING_KEY = "kpii_mapping"
_DEFAULT_POLICY = "/app/policies/default.yaml"


class KoreanPIIGuardrail(CustomGuardrail):
    """요청 본문의 한국어 PII를 탐지해 마스킹/차단하는 LiteLLM guardrail."""

    def __init__(self, *, ner_client=None, **kwargs: Any) -> None:
        # policy_path 는 litellm_params(config) 또는 환경변수로 주입. 나머지는 super 로 전달.
        policy_path = kwargs.pop("policy_path", None) or os.environ.get(
            "KPII_POLICY_PATH", _DEFAULT_POLICY
        )
        self.policy = Policy.load(policy_path)
        # NER 활성 시 Presidio 클라이언트 구성(테스트는 ner_client 주입 가능, 키워드 전용)
        self._ner_client = ner_client
        if self._ner_client is None and self.policy.ner.enabled:
            from kpii.detectors.presidio_client import PresidioClient

            self._ner_client = PresidioClient(
                self.policy.ner.api_base, self.policy.ner.timeout_ms
            )
        super().__init__(**kwargs)
        # 선택: KPII_METRICS_PORT 설정 시 사이드 포트로 /metrics 노출
        port = os.environ.get("KPII_METRICS_PORT")
        if port:
            try:
                metrics.start_server(int(port))
            except Exception:  # 이미 기동됐거나 포트 사용 중이면 무시
                pass

    def _emit_audit(self, event) -> None:
        # §7.1 JSONL 기록 (kpii.audit 로거). 원문/매핑/위치 없음.
        log_event(event)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        try:
            session = MaskingSession()
            t0 = time.perf_counter()
            if self.policy.ner.enabled and self._ner_client is not None:
                result = await process_request_async(data, self.policy, session, self._ner_client)
            else:
                result = process_request(data, self.policy, session)
            latency_s = time.perf_counter() - t0

            # 감사 이벤트 + 메트릭 (원문 없이 카운트/타입/지연만 — §7 무유출)
            event = event_from_result(
                request_id=str(data.get("litellm_call_id") or ""),
                endpoint=str(call_type),
                result=result,
                model=data.get("model"),
                stream=bool(data.get("stream")),
                ner_used=self.policy.ner.enabled and self._ner_client is not None,
                scan_latency_ms=round(latency_s * 1000, 2),
            )
            self._emit_audit(event)
            metrics.record_scan(result, lambda e: self.policy.action_for(e).value, latency_s)
            if (
                self.policy.injection.enabled
                and result.injection_score >= self.policy.injection.threshold
            ):
                metrics.incr_injection(self.policy.injection.action)

            if result.blocked:
                # litellm ProxyException 은 openai_code 를 응답 본문에 노출하지 않고 code 엔 HTTP
                # 상태(400)를 넣는다(라이브 확인). 클라이언트가 차단 사유를 기계적으로 식별하도록
                # 안정 마커를 메시지에 포함한다: PII 는 [pii_blocked], 인젝션 단독은 [injection_blocked].
                pii_ents = [e for e in result.block_entities if e != INJECTION_MARKER]
                if pii_ents:
                    labels = ", ".join(f"{e}({_ENTITY_LABELS.get(e, e)})" for e in pii_ents)
                    message = (
                        f"[pii_blocked] 요청에 차단 대상 민감정보가 포함되어 있습니다: {labels}. "
                        "해당 값을 제거한 뒤 다시 시도하세요."
                    )
                    marker = "pii_blocked"
                else:
                    message = (
                        "[injection_blocked] 요청에서 프롬프트 인젝션 의심 패턴이 감지되어 "
                        "정책상 차단되었습니다."
                    )
                    marker = "injection_blocked"
                raise ProxyException(
                    message=message,
                    type="invalid_request_error",
                    param=None,
                    code=400,
                    openai_code=marker,
                )

            # Phase 3 복원용 매핑 전달 (요청 스코프, 저장/로그 금지 — D4)
            data.setdefault("metadata", {})[MAPPING_KEY] = result.mapping
            # TODO(Phase 5): result(detections/actions)로 감사 이벤트 기록
            return data

        except ProxyException:
            raise
        except NerUnavailable:
            # NER 사이드카 불가 + 정책 ner.on_failure=block → 요청 차단(503)
            raise ProxyException(
                message="[ner_unavailable] PII 탐지(NER) 서비스에 연결할 수 없어 정책상 요청을 차단합니다.",
                type="api_error",
                param=None,
                code=503,
                openai_code="ner_unavailable",
            )
        except Exception:
            # 필터 자체 오류: 정책에 따라 fail-closed(block) 또는 degrade(allow) — §D5
            if self.policy.on_internal_error == "block":
                raise ProxyException(
                    message="요청 필터링 중 내부 오류가 발생했습니다.",
                    type="invalid_request_error",
                    param=None,
                    code=500,
                    openai_code="pii_filter_error",
                )
            return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        # 비스트리밍 응답 복원: choices[].message.content 및 tool_calls arguments (§5).
        mapping = self._mapping_from(data)
        if not mapping:
            return response
        for choice in getattr(response, "choices", None) or []:
            msg = getattr(choice, "message", None)
            if msg is None:
                continue
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                msg.content = restore(content, mapping)
            for tc in getattr(msg, "tool_calls", None) or []:
                fn = getattr(tc, "function", None)
                args = getattr(fn, "arguments", None) if fn is not None else None
                if isinstance(args, str):
                    fn.arguments = restore(args, mapping)
        return response

    async def async_post_call_streaming_iterator_hook(self, user_api_key_dict, response, request_data):
        # 스트리밍 복원: 델타를 StreamRestorer 로 통과. 매핑 없으면 버퍼링 없이 통과(지연 0).
        # 단일 choice(n=1) 가정 — 스트리밍 복원의 일반 케이스.
        mapping = self._mapping_from(request_data)
        if not mapping:
            async for chunk in response:
                yield chunk
            return
        restorer = StreamRestorer(mapping)
        async for chunk in response:
            choices = getattr(chunk, "choices", None) or []
            if choices:
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None) if delta is not None else None
                if isinstance(content, str) and content:
                    delta.content = restorer.push(content)
                if delta is not None and getattr(choices[0], "finish_reason", None) is not None:
                    leftover = restorer.flush()      # 종료 청크에 남은 버퍼 방출
                    if leftover:
                        delta.content = (getattr(delta, "content", None) or "") + leftover
            yield chunk

    @staticmethod
    def _mapping_from(container) -> dict:
        meta = (container or {}).get("metadata") or {}
        return meta.get(MAPPING_KEY) or {}
