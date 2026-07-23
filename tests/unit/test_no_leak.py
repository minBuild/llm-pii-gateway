"""무유출 테스트 (DESIGN §7 / Phase 5 DoD): 감사 로그·메트릭 어디에도 원문 PII 없음.

라이브 스택(litellm 로그·spend 테이블) 무유출은 통합/로컬에서, 여기선 컴포넌트(감사+메트릭)
레벨을 강하게 검증한다.
"""

import logging
import pathlib

import pytest

pytest.importorskip("prometheus_client")

from kpii import MaskingSession, Policy, metrics  # noqa: E402
from kpii.audit import event_from_result, log_event  # noqa: E402
from kpii.openai_gateway import process_request  # noqa: E402
from tests.util import gen  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY = Policy.load(ROOT / "policies" / "default.yaml")


def _haystack(caplog) -> str:
    audit = "\n".join(r.message for r in caplog.records if r.name == "kpii.audit")
    return audit + "\n" + metrics.render().decode("utf-8")


def _emit(result, caplog):
    with caplog.at_level(logging.INFO, logger="kpii.audit"):
        log_event(event_from_result("r", "/v1/chat/completions", result, model="m"))
    metrics.record_scan(result, lambda e: POLICY.action_for(e).value, 0.002)


def test_masked_and_log_only_values_never_leak(caplog):
    mask_vals = ["010-1234-5678", "hong@example.com", gen.gen_card()]
    brn = gen.gen_brn()  # LOG_ONLY → 본문엔 남지만 감사/메트릭엔 없어야
    text = f"폰 {mask_vals[0]}, 메일 {mask_vals[1]}, 카드 {mask_vals[2]}, 사업자 {brn}"
    body = {"model": "m", "messages": [{"role": "user", "content": text}]}

    result = process_request(body, POLICY, MaskingSession())
    _emit(result, caplog)

    hay = _haystack(caplog)
    for v in mask_vals + [brn]:
        assert v not in hay, f"감사/메트릭에 원문 유출: {v[:4]}..."

    masked = body["messages"][0]["content"]
    for v in mask_vals:
        assert v not in masked          # MASK → 본문에서 사라짐
    assert brn in masked                # LOG_ONLY → 본문 유지(정책상 의도)


def test_blocked_request_value_never_leaks(caplog):
    rrn = gen.gen_rrn()
    body = {"model": "m", "messages": [{"role": "user", "content": f"주민 {rrn}"}]}

    result = process_request(body, POLICY, MaskingSession())
    assert result.blocked
    _emit(result, caplog)

    assert rrn not in _haystack(caplog)   # 차단돼도 원문은 감사/메트릭에 없음
