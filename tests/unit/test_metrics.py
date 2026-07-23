"""Prometheus 메트릭 테스트 (DESIGN §7.2)."""

import pathlib

import pytest

pytest.importorskip("prometheus_client")

from kpii import MaskingSession, Policy, metrics  # noqa: E402
from kpii.openai_gateway import process_request  # noqa: E402
from tests.util import gen  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY = Policy.load(ROOT / "policies" / "default.yaml")


def _action_of(entity: str) -> str:
    return POLICY.action_for(entity).value


def test_render_exposes_kpii_metrics_without_pii():
    body = {"model": "m", "messages": [{"role": "user", "content": "폰 010-1234-5678"}]}
    result = process_request(body, POLICY, MaskingSession())
    metrics.record_scan(result, _action_of, 0.003)

    out = metrics.render().decode("utf-8")
    assert "kpii_detections_total" in out
    assert "kpii_scan_latency_seconds" in out
    assert 'entity="PHONE"' in out
    assert 'action="mask"' in out
    assert "010-1234-5678" not in out          # 라벨/값에 원문 없음


def test_blocked_and_ner_failure_counters_present():
    body = {"model": "m", "messages": [{"role": "user", "content": f"주민 {gen.gen_rrn()}"}]}
    result = process_request(body, POLICY, MaskingSession())     # RRN → blocked
    metrics.record_scan(result, _action_of, 0.001)
    metrics.incr_ner_failure()

    out = metrics.render().decode("utf-8")
    assert "kpii_blocked_requests_total" in out
    assert "kpii_ner_failures_total" in out
