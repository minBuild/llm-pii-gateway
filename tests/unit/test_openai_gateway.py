"""요청 본문 스캔/마스킹/차단 코어 테스트 (DESIGN §5.5, LiteLLM 무의존)."""

import copy
import pathlib

from kpii import MaskingSession, Policy
from kpii.openai_gateway import process_request
from tests.util import gen

ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY = Policy.load(ROOT / "policies" / "default.yaml")


def _proc(body: dict):
    return process_request(body, POLICY, MaskingSession())


def test_chat_phone_masked_in_place():
    body = {"model": "m", "messages": [{"role": "user", "content": "연락처 010-1234-5678 로"}]}
    r = _proc(body)
    assert not r.blocked
    assert "010-1234-5678" not in body["messages"][0]["content"]
    assert "[PHONE_1]" in body["messages"][0]["content"]
    assert "[PHONE_1]" in r.mapping
    assert r.actions["masked"] == 1


def test_chat_rrn_blocked_and_body_unchanged():
    original = {"model": "m", "messages": [{"role": "user", "content": f"주민 {gen.gen_rrn()}"}]}
    body = copy.deepcopy(original)
    r = _proc(body)
    assert r.blocked
    assert r.block_entities == ["RRN"]
    assert body == original                      # 차단 시 본문 미변형 (§5.4)
    assert r.mapping == {}


def test_all_scan_fields_masked():
    body = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "담당자 hong@example.com"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "내 번호 010-1234-5678"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"type": "function", "function": {"name": "f",
                     "arguments": '{"phone": "010-9876-5432"}'}}
                ],
            },
            {"role": "tool", "content": "결과 kim@corp.com"},
        ],
    }
    r = _proc(body)
    assert not r.blocked
    assert "hong@example.com" not in body["messages"][0]["content"]           # system
    assert "010-1234-5678" not in body["messages"][1]["content"][0]["text"]   # multimodal text
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png")  # image 통과
    assert r.image_passthrough
    args = body["messages"][2]["tool_calls"][0]["function"]["arguments"]
    assert "010-9876-5432" not in args and "[PHONE_" in args                  # tool_calls arguments
    assert "kim@corp.com" not in body["messages"][3]["content"]               # tool 메시지


def test_embeddings_input_str_and_list():
    b1 = {"model": "e", "input": "메일 a@b.com"}
    _proc(b1)
    assert "a@b.com" not in b1["input"]

    b2 = {"model": "e", "input": ["폰 010-1234-5678", "noPII"]}
    _proc(b2)
    assert "010-1234-5678" not in b2["input"][0]
    assert b2["input"][1] == "noPII"


def test_no_pii_unchanged():
    original = {"model": "m", "messages": [{"role": "user", "content": "오늘 날씨 어때?"}]}
    body = copy.deepcopy(original)
    r = _proc(body)
    assert not r.blocked
    assert body == original
    assert not r.mapping


def test_log_only_brn_not_masked():
    brn = gen.gen_brn()
    body = {"model": "m", "messages": [{"role": "user", "content": f"사업자 {brn} 문의드립니다"}]}
    r = _proc(body)
    assert not r.blocked
    assert brn in body["messages"][0]["content"]     # LOG_ONLY → 원문 유지
    assert r.detections.get("BRN") == 1
    assert r.actions["log_only"] == 1
