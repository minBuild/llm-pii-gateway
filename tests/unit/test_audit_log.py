"""감사 로거(JSONL) 테스트 (DESIGN §7.1)."""

import json
import logging
import pathlib

from kpii import MaskingSession, Policy
from kpii.audit import event_from_result, log_event
from kpii.openai_gateway import process_request

ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY = Policy.load(ROOT / "policies" / "default.yaml")


def _audit_lines(caplog) -> list[str]:
    return [r.message for r in caplog.records if r.name == "kpii.audit"]


def test_log_event_is_jsonl_with_counts_only(caplog):
    body = {"model": "m", "messages": [{"role": "user", "content": "폰 010-1234-5678, 메일 a@b.com"}]}
    result = process_request(body, POLICY, MaskingSession())
    ev = event_from_result("req-1", "/v1/chat/completions", result, model="m", stream=True)

    with caplog.at_level(logging.INFO, logger="kpii.audit"):
        log_event(ev)

    lines = _audit_lines(caplog)
    assert len(lines) == 1
    d = json.loads(lines[0])                      # 유효한 JSON 한 줄
    assert d["detections"]["PHONE"] == 1
    assert d["detections"]["EMAIL"] == 1
    assert d["actions"]["masked"] == 2
    assert d["blocked"] is False
    assert d["ts"]                                # 로깅 시 채워짐
    # 원문/매핑/위치 없음
    assert "010-1234-5678" not in lines[0]
    assert "a@b.com" not in lines[0]
    assert "mapping" not in d and "start" not in lines[0]
