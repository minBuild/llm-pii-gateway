"""감사 이벤트 (DESIGN §7.1).

Phase 2에서는 dataclass 정의 + 생성만 담당한다. stdout JSONL 로거 연결은 Phase 5.

금지 필드(§7.1): PII 원문, 마스킹 전 텍스트, 매핑, 탐지 위치(start/end).
이 dataclass에는 애초에 그런 필드를 두지 않는다 — 카운트/타입/메타데이터만.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


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
        scan_latency_ms=scan_latency_ms,
    )
