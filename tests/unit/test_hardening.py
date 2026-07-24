"""하드닝: 위협 모델 잔여 리스크 정리 (R4 입력 길이, R5 필드 커버리지, R6 멀티 choice 복원).

R3(관측 실패가 fail-open 을 유발하지 않음)은 guardrail(litellm) 경로라 tests/unit/test_guardrail.py
에 게이트 테스트로 둔다.
"""

from __future__ import annotations

from kpii.masking import MaskingSession, StreamRestorer
from kpii.openai_gateway import process_request
from kpii.policy import Policy

_MASK = Policy.from_dict({
    "version": 1, "default_action": "mask",
    "entities": {"PHONE": {"action": "mask"}, "RRN": {"action": "block"}},
})
_CAP = Policy.from_dict({
    "version": 1, "default_action": "mask",
    "entities": {"PHONE": {"action": "mask"}},
    "max_scan_chars": 50,
})


# ---------------- R5: Responses API input_text 파트도 스캔 ----------------


def test_r5_input_text_part_is_masked():
    body = {"messages": [{"role": "user", "content": [
        {"type": "input_text", "text": "내 번호 010-1234-5678"},
    ]}]}
    res = process_request(body, _MASK, MaskingSession())
    out = body["messages"][0]["content"][0]["text"]
    assert res.detections.get("PHONE", 0) == 1
    assert "[PHONE_" in out and "010-1234-5678" not in out


def test_r5_plain_text_part_still_works():
    body = {"messages": [{"role": "user", "content": [
        {"type": "text", "text": "번호 010-1234-5678"},
    ]}]}
    res = process_request(body, _MASK, MaskingSession())
    assert res.detections.get("PHONE", 0) == 1


# ---------------- R4: 입력 길이 상한 초과 시 차단 ----------------


def test_r4_oversized_blocked():
    body = {"messages": [{"role": "user", "content": "가" * 51}]}   # cap=50 초과
    res = process_request(body, _CAP, MaskingSession())
    assert res.blocked
    assert "OVERSIZED_INPUT" in res.block_entities


def test_r4_within_cap_passes():
    body = {"messages": [{"role": "user", "content": "짧은 요청"}]}
    res = process_request(body, _CAP, MaskingSession())
    assert not res.blocked


def test_r4_disabled_by_default_no_cap():
    # 기본 정책(max_scan_chars=0)은 길이 제한 없음
    body = {"messages": [{"role": "user", "content": "가" * 10000}]}
    res = process_request(body, _MASK, MaskingSession())
    assert not res.blocked


# ---------------- R6: n>1 스트리밍은 choice 별 독립 복원 ----------------


def test_r6_independent_restorers_per_choice():
    # 서로 다른 choice 스트림이 독립 복원기로 각각 올바르게 복원되는지(가드레일 훅이 쓰는 메커니즘).
    mapping = {"[PHONE_1]": "010-1234-5678", "[EMAIL_1]": "a@b.com"}
    r0, r1 = StreamRestorer(mapping), StreamRestorer(mapping)
    # choice 0 은 PHONE, choice 1 은 EMAIL 을 청크 경계로 쪼개 흘려보냄
    out0 = r0.push("전화 [PHO") + r0.push("NE_1] 임") + r0.flush()
    out1 = r1.push("메일 [EMA") + r1.push("IL_1] 임") + r1.flush()
    assert out0 == "전화 010-1234-5678 임"
    assert out1 == "메일 a@b.com 임"
