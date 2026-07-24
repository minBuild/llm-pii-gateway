"""감사 이벤트 (DESIGN §7.1).

Phase 2에서는 dataclass 정의 + 생성만 담당한다. stdout JSONL 로거 연결은 Phase 5.

금지 필드(§7.1): PII 원문, 마스킹 전 텍스트, 매핑, 탐지 위치(start/end).
이 dataclass에는 애초에 그런 필드를 두지 않는다 — 카운트/타입/메타데이터만.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import asdict, dataclass, field

# 감사 로거. 앱/어댑터가 stdout StreamHandler 를 붙인다(수집은 표준 파이프라인에 위임).
audit_logger = logging.getLogger("kpii.audit")


@dataclass
class AuditEvent:
    request_id: str
    endpoint: str
    model: str | None = None
    key_alias: str | None = None
    stream: bool = False
    detections: dict[str, int] = field(default_factory=dict)   # 엔티티별 탐지 수(원문 없음)
    actions: dict[str, int] = field(default_factory=dict)      # masked/blocked/log_only
    blocked: bool = False
    ner_used: bool = False
    ner_degraded: bool = False
    image_passthrough: bool = False
    injection_score: int = 0                                   # 프롬프트 인젝션 점수(원문 없음)
    injection_categories: list[str] = field(default_factory=list)   # 발화 카테고리만
    scan_latency_ms: float | None = None
    ts: str | None = None                                      # Phase 5 로거에서 채움

    def to_dict(self) -> dict:
        return asdict(self)


def event_from_result(
    request_id: str,
    endpoint: str,
    result,
    *,
    model: str | None = None,
    key_alias: str | None = None,
    stream: bool = False,
    ner_used: bool = False,
    ner_degraded: bool = False,
    scan_latency_ms: float | None = None,
) -> AuditEvent:
    """openai_gateway.ProcessResult 로부터 감사 이벤트를 만든다(원문 미포함)."""
    return AuditEvent(
        request_id=request_id,
        endpoint=endpoint,
        model=model,
        key_alias=key_alias,
        stream=stream,
        detections=dict(result.detections),
        actions=dict(result.actions),
        blocked=result.blocked,
        ner_used=ner_used,
        ner_degraded=ner_degraded,
        image_passthrough=result.image_passthrough,
        injection_score=getattr(result, "injection_score", 0),
        injection_categories=list(getattr(result, "injection_categories", []) or []),
        scan_latency_ms=scan_latency_ms,
    )


def log_event(event: AuditEvent, logger: logging.Logger | None = None) -> None:
    """감사 이벤트를 JSONL 한 줄로 기록(§7.1). 원문/매핑/위치는 애초에 이벤트에 없다."""
    if event.ts is None:
        event.ts = datetime.datetime.now().astimezone().isoformat()
    (logger or audit_logger).info(json.dumps(event.to_dict(), ensure_ascii=False))
