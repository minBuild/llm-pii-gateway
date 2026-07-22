"""OpenAI 호환 요청 본문을 걷어 PII를 스캔/마스킹/차단하는 게이트웨이 로직.

LiteLLM 무의존(순수 파이썬). LiteLLM guardrail 어댑터
(litellm/custom_guardrails/kpii_guardrail.py)가 이 함수를 호출한다 — 설계 D8/§6.3의
"얇은 어댑터, 두꺼운 코어" 원칙. HTTP/예외 변환은 어댑터가, 탐지/마스킹 판단은 여기가 담당.

스캔 범위(§5.5):
- chat/completions: messages[].content(문자열 또는 multimodal text part),
  messages[].tool_calls[].function.arguments(JSON 문자열), tool 롤 메시지 content
- completions: prompt
- embeddings: input(문자열 또는 문자열 배열) — 마스킹만(복원 불필요)
- 이미지/파일 part 는 통과(감사에 image_passthrough 표기, §5.5)
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from .engine import scan
from .masking import MaskingSession
from .policy import Policy
from .types import Action

# 텍스트 필드 하나: 현재 값 + 마스킹 결과를 되쓸 setter
_Field = tuple[str, Callable[[str], None]]


@dataclass
class ProcessResult:
    """요청 처리 결과. mapping 에는 PII 원문이 있으므로 로그/저장 금지(D4)."""

    blocked: bool
    block_entities: list[str]              # 차단된 엔티티 타입(원문 없음)
    detections: dict[str, int]             # 엔티티별 탐지 수(감사용)
    actions: dict[str, int]                # {"masked","blocked","log_only"} 카운트
    image_passthrough: bool = False
    mapping: dict[str, str] = field(default_factory=dict)


def _setter(container: dict | list, key) -> Callable[[str], None]:
    def _set(value: str) -> None:
        container[key] = value
    return _set


def _iter_scan_fields(body: dict) -> tuple[list[_Field], bool]:
    """스캔 대상 (텍스트, setter) 목록과 image_passthrough 여부를 반환."""
    fields: list[_Field] = []
    image_seen = False

    messages = body.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, str):
                fields.append((content, _setter(msg, "content")))
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type")
                    if ptype == "text" and isinstance(part.get("text"), str):
                        fields.append((part["text"], _setter(part, "text")))
                    elif ptype in ("image_url", "input_image", "image"):
                        image_seen = True   # 이미지는 통과(§5.5)
            # tool_calls 의 function.arguments(JSON 문자열)
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") if isinstance(tc, dict) else None
                if isinstance(fn, dict) and isinstance(fn.get("arguments"), str):
                    fields.append((fn["arguments"], _setter(fn, "arguments")))

    prompt = body.get("prompt")            # completions
    if isinstance(prompt, str):
        fields.append((prompt, _setter(body, "prompt")))

    inp = body.get("input")                # embeddings
    if isinstance(inp, str):
        fields.append((inp, _setter(body, "input")))
    elif isinstance(inp, list):
        for i, item in enumerate(inp):
            if isinstance(item, str):
                fields.append((item, _setter(inp, i)))

    return fields, image_seen


def process_request(body: dict, policy: Policy, session: MaskingSession) -> ProcessResult:
    """요청 본문을 in-place 로 마스킹하고 결과를 반환.

    BLOCK 엔티티가 하나라도 있으면 본문을 **변형하지 않고** blocked 결과를 돌려준다
    (업스트림 호출 없이 어댑터가 400 반환, §5.4). 그 외에는 MASK 엔티티만 치환하고
    LOG_ONLY 는 원문 그대로 둔다.
    """
    fields, image_passthrough = _iter_scan_fields(body)

    scanned: list[tuple[str, Callable[[str], None], list]] = []
    detections: Counter[str] = Counter()
    for text, setter in fields:
        dets = scan(text, policy)
        scanned.append((text, setter, dets))
        detections.update(d.entity for d in dets)

    # BLOCK 검사(전체 필드) — 하나라도 있으면 변형 없이 차단
    block_entities = sorted(
        {
            d.entity
            for _, _, dets in scanned
            for d in dets
            if policy.action_for(d.entity) is Action.BLOCK
        }
    )
    if block_entities:
        return ProcessResult(
            blocked=True,
            block_entities=block_entities,
            detections=dict(detections),
            actions={"masked": 0, "blocked": int(sum(detections.values())), "log_only": 0},
            image_passthrough=image_passthrough,
        )

    # MASK 적용 (LOG_ONLY 는 그대로)
    actions: Counter[str] = Counter()
    for text, setter, dets in scanned:
        masks = [d for d in dets if policy.action_for(d.entity) is Action.MASK]
        for d in dets:
            action = policy.action_for(d.entity)
            if action is Action.MASK:
                actions["masked"] += 1
            elif action is Action.LOG_ONLY:
                actions["log_only"] += 1
        if masks:
            setter(session.mask(text, masks))

    return ProcessResult(
        blocked=False,
        block_entities=[],
        detections=dict(detections),
        actions={"masked": actions["masked"], "blocked": 0, "log_only": actions["log_only"]},
        image_passthrough=image_passthrough,
        mapping=session.mapping,
    )
