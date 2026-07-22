"""감사 이벤트 무유출 테스트 (DESIGN §7.1). Phase 5 무유출 테스트의 축소판."""

import pathlib

from kpii import MaskingSession, Policy
from kpii.audit import event_from_result
from kpii.openai_gateway import process_request
from tests.util import gen

ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY = Policy.load(ROOT / "policies" / "default.yaml")


def test_event_has_counts_no_raw_pii():
    body = {"model": "m", "messages": [{"role": "user", "content": "폰 010-1234-5678, 메일 a@b.com"}]}
    result = process_request(body, POLICY, MaskingSession())
    ev = event_from_result("req-1", "/v1/chat/completions", result, model="m", stream=True)
    d = ev.to_dict()

    assert d["detections"].get("PHONE") == 1
    assert d["detections"].get("EMAIL") == 1
    assert d["actions"]["masked"] >= 2
    # 원문/매핑/위치가 이벤트에 절대 없어야 한다
    blob = str(d)
    assert "010-1234-5678" not in blob
    assert "a@b.com" not in blob
    assert "mapping" not in d
    assert "start" not in blob and "end" not in d


def test_blocked_event():
    body = {"model": "m", "messages": [{"role": "user", "content": f"주민 {gen.gen_rrn()}"}]}
    result = process_request(body, POLICY, MaskingSession())
    ev = event_from_result("req-2", "/v1/chat/completions", result)
    assert ev.blocked is True
    assert ev.actions["blocked"] >= 1
