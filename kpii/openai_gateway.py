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

import asyncio
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from .engine import scan, scan_async
from .masking import MaskingSession
from .normalize import normalize_for_detection
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

    # 탐지 회피 방지: 정규화한 텍스트로 탐지·마스킹·전달을 일관되게(스팬 정합성). THREAT_MODEL R1.
    fields = [(normalize_for_detection(text), setter) for text, setter in fields]
    return fields, image_seen


def process_request(body: dict, policy: Policy, session: MaskingSession) -> ProcessResult:
    """L1 전용(동기). NER 비활성 경로. 본문을 in-place 로 마스킹/차단."""
    fields, image_passthrough = _iter_scan_fields(body)
    scanned = [(text, setter, scan(text, policy)) for text, setter in fields]
    return _finalize(scanned, policy, session, image_passthrough)


async def process_request_async(
    body: dict, policy: Policy, session: MaskingSession, ner_client=None
) -> ProcessResult:
    """L1+L2(비동기). NER 활성 경로. 필드별 NER 호출을 동시에 실행해 지연을 최소화한다.

    NER 실패 시 scan_async 가 정책(ner.on_failure)에 따라 degrade 하거나 NerUnavailable 를
    전파한다(어댑터가 503 차단).
    """
    fields, image_passthrough = _iter_scan_fields(body)
    dets_per_field = await asyncio.gather(
        *(scan_async(text, policy, ner_client) for text, _ in fields)
    )
    scanned = [
        (text, setter, dets) for (text, setter), dets in zip(fields, dets_per_field)
    ]
    return _finalize(scanned, policy, session, image_passthrough)


def _finalize(
    scanned: list[tuple[str, Callable[[str], None], list]],
    policy: Policy,
    session: MaskingSession,
    image_passthrough: bool,
) -> ProcessResult:
    """스캔 결과(필드별)로 BLOCK 검사 → MASK 적용 → 결과 반환 (§5.4).

    BLOCK 엔티티가 하나라도 있으면 본문을 **변형하지 않고** blocked 결과를 돌려준다.
    """
    detections: Counter[str] = Counter()
    for _, _, dets in scanned:
        detections.update(d.entity for d in dets)

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
