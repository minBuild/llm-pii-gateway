"""NER(L2) 파이프라인 오프라인 테스트: scan_async + process_request_async (모킹).

실제 Presidio 없이, mock ner_client 로 L1+L2 병합·degrade·block 을 검증.
"""

import asyncio

import pytest

from kpii import MaskingSession, Policy
from kpii.engine import scan_async
from kpii.openai_gateway import process_request_async
from kpii.types import Detection, NerUnavailable


def _policy(on_failure: str = "degrade") -> Policy:
    return Policy.from_dict({
        "version": 1,
        "default_action": "mask",
        "entities": {
            "RRN": {"action": "block"},
            "PHONE": {"action": "mask"},
            "PERSON": {"action": "mask"},
            "LOCATION": {"action": "mask"},
        },
        "on_internal_error": "block",
        "ner": {"enabled": True, "on_failure": on_failure},
    })


class _MockNer:
    def __init__(self, dets_fn=None, fail: bool = False):
        self._fn = dets_fn
        self._fail = fail

    async def detect(self, text: str):
        if self._fail:
            raise NerUnavailable("sidecar down")
        return self._fn(text) if self._fn else []


def test_scan_async_merges_l1_and_l2():
    text = "김민수 010-1234-5678"
    ner = _MockNer(lambda t: [Detection("PERSON", 0, 3, t[0:3], 0.9, "ner")])
    dets = asyncio.run(scan_async(text, _policy(), ner))
    assert {d.entity for d in dets} == {"PERSON", "PHONE"}


def test_scan_async_degrades_on_ner_failure():
    dets = asyncio.run(scan_async("김민수 010-1234-5678", _policy("degrade"), _MockNer(fail=True)))
    assert {d.entity for d in dets} == {"PHONE"}          # L1 만, 예외 없음


def test_scan_async_blocks_on_ner_failure():
    with pytest.raises(NerUnavailable):
        asyncio.run(scan_async("김민수", _policy("block"), _MockNer(fail=True)))


def test_process_request_async_masks_person_and_phone():
    ner = _MockNer(lambda t: [Detection("PERSON", 0, 3, t[0:3], 0.9, "ner")] if t.startswith("김민수") else [])
    body = {"model": "m", "messages": [{"role": "user", "content": "김민수 고객 연락처 010-1234-5678"}]}
    r = asyncio.run(process_request_async(body, _policy(), MaskingSession(), ner))
    content = body["messages"][0]["content"]
    assert "김민수" not in content and "[PERSON_1]" in content
    assert "010-1234-5678" not in content and "[PHONE_1]" in content
    assert not r.blocked
    assert r.detections.get("PERSON") == 1


def test_process_request_async_block_policy_ner_down_raises():
    body = {"model": "m", "messages": [{"role": "user", "content": "김민수"}]}
    with pytest.raises(NerUnavailable):
        asyncio.run(process_request_async(body, _policy("block"), MaskingSession(), _MockNer(fail=True)))
