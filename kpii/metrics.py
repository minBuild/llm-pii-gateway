"""Prometheus 메트릭 (DESIGN §7.2).

prometheus_client 가 없으면 전부 no-op(코어는 하드 의존 안 함). 라벨은 엔티티 타입/액션
같은 저카디널리티 값만 — **원문/매핑은 라벨에 절대 넣지 않는다**(§7 무유출).
"""

from __future__ import annotations

from collections.abc import Callable

try:
    from prometheus_client import Counter, Histogram, generate_latest, start_http_server

    _ENABLED = True
except ImportError:  # prometheus_client 미설치 → 메트릭 비활성
    _ENABLED = False

if _ENABLED:
    _detections = Counter(
        "kpii_detections_total", "탐지된 PII 수 (엔티티/액션별)", ["entity", "action"]
    )
    _blocked = Counter("kpii_blocked_requests_total", "PII 로 차단된 요청 수")
    _latency = Histogram("kpii_scan_latency_seconds", "요청 스캔 지연(초)")
    _ner_failures = Counter("kpii_ner_failures_total", "NER 사이드카 호출 실패 수")


def record_scan(result, action_of: Callable[[str], str], latency_s: float) -> None:
    """ProcessResult 로 메트릭 기록. action_of(entity)->action 문자열."""
    if not _ENABLED:
        return
    _latency.observe(latency_s)
    if result.blocked:
        _blocked.inc()
    for entity, count in result.detections.items():
        _detections.labels(entity=entity, action=action_of(entity)).inc(count)


def incr_ner_failure() -> None:
    if _ENABLED:
        _ner_failures.inc()


def start_server(port: int) -> bool:
    if _ENABLED:
        start_http_server(port)
        return True
    return False


def render() -> bytes:
    """현재 메트릭 텍스트(테스트/디버그용)."""
    return generate_latest() if _ENABLED else b""
