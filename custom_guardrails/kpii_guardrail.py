"""LiteLLM 커스텀 guardrail 어댑터 (DESIGN §6.3).

얇은 어댑터: 탐지/마스킹 판단은 kpii.openai_gateway 가, HTTP/예외 변환과 매핑 전달은 여기가.
훅 시그니처는 litellm 1.93.0 실제 소스에서 검증(docs/NOTES.md).

- Phase 2: async_pre_call_hook — 스캔·마스킹·차단·매핑 저장.
- Phase 3: async_post_call_success_hook / async_post_call_streaming_iterator_hook 에서 복원.
"""

from __future__ import annotations

import os
from typing import Any

from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.proxy._types import ProxyException

from kpii.audit import event_from_result
from kpii.masking import MaskingSession
from kpii.openai_gateway import process_request
from kpii.policy import Policy

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
}
MAPPING_KEY = "kpii_mapping"
_DEFAULT_POLICY = "/app/policies/default.yaml"


class KoreanPIIGuardrail(CustomGuardrail):
    """요청 본문의 한국어 PII를 탐지해 마스킹/차단하는 LiteLLM guardrail."""

    def __init__(self, **kwargs: Any) -> None:
        # policy_path 는 litellm_params(config) 또는 환경변수로 주입. 나머지는 super 로 전달.
        policy_path = kwargs.pop("policy_path", None) or os.environ.get(
            "KPII_POLICY_PATH", _DEFAULT_POLICY
        )
        self.policy = Policy.load(policy_path)
        super().__init__(**kwargs)

    def _emit_audit(self, event) -> None:
        # Phase 5: §7.1 JSONL stdout 기록 + 메트릭. 지금은 생성 지점만(소비 안 함).
        return None

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        try:
            session = MaskingSession()
            result = process_request(data, self.policy, session)

            # 감사 이벤트 생성 지점 (로거 연결은 Phase 5 — no-op sink)
            self._emit_audit(
                event_from_result(
                    request_id=str(data.get("litellm_call_id") or ""),
                    endpoint=str(call_type),
                    result=result,
                    model=data.get("model"),
                    stream=bool(data.get("stream")),
                )
            )

            if result.blocked:
                labels = ", ".join(
                    f"{e}({_ENTITY_LABELS.get(e, e)})" for e in result.block_entities
                )
                raise ProxyException(
                    message=(
                        f"요청에 차단 대상 민감정보가 포함되어 있습니다: {labels}. "
                        "해당 값을 제거한 뒤 다시 시도하세요."
                    ),
                    type="invalid_request_error",
                    param=None,
                    code=400,
                    openai_code="pii_blocked",
                )

            # Phase 3 복원용 매핑 전달 (요청 스코프, 저장/로그 금지 — D4)
            data.setdefault("metadata", {})[MAPPING_KEY] = result.mapping
            # TODO(Phase 5): result(detections/actions)로 감사 이벤트 기록
            return data

        except ProxyException:
            raise
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
        # Phase 3: data["metadata"][MAPPING_KEY] 로 response 텍스트 복원
        return response

    async def async_post_call_streaming_iterator_hook(self, user_api_key_dict, response, request_data):
        # Phase 3: StreamRestorer 로 델타 복원
        async for chunk in response:
            yield chunk
