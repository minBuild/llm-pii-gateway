"""LiteLLM guardrail 어댑터 훅 테스트 — 도커/프록시 없이 훅을 직접 호출.

litellm 은 proxy-side 의존성이라 코어 단위테스트에는 없어도 된다. 미설치 시 이 모듈
전체를 skip 한다(`pip install -e ".[proxy]"` 로 활성화).
"""

import asyncio
import pathlib

import pytest

pytest.importorskip("litellm")  # litellm 없으면 모듈 전체 skip

from litellm.proxy._types import ProxyException  # noqa: E402

from custom_guardrails.kpii_guardrail import MAPPING_KEY, KoreanPIIGuardrail  # noqa: E402
from tests.util import gen  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY_PATH = str(ROOT / "policies" / "default.yaml")


def _pre(data: dict, call_type: str = "acompletion") -> dict:
    guard = KoreanPIIGuardrail(policy_path=POLICY_PATH, guardrail_name="kpii")
    return asyncio.run(guard.async_pre_call_hook(None, None, data, call_type))


def test_pre_call_masks_phone_and_passes_mapping():
    data = {"model": "m", "messages": [{"role": "user", "content": "연락처 010-1234-5678"}]}
    out = _pre(data)
    assert "010-1234-5678" not in out["messages"][0]["content"]
    assert "[PHONE_1]" in out["messages"][0]["content"]
    assert "[PHONE_1]" in out["metadata"][MAPPING_KEY]   # Phase 3 복원용 매핑 전달


def test_pre_call_blocks_rrn_without_leaking():
    rrn = gen.gen_rrn()
    data = {"model": "m", "messages": [{"role": "user", "content": f"주민 {rrn}"}]}
    with pytest.raises(ProxyException) as ei:
        _pre(data)
    exc = ei.value
    assert exc.openai_code == "pii_blocked"
    assert exc.type == "invalid_request_error"
    assert "RRN" in exc.message
    assert rrn not in str(exc)                            # 예외에 원문 미유출


def test_pre_call_passthrough_no_pii():
    data = {"model": "m", "messages": [{"role": "user", "content": "오늘 날씨 어때?"}]}
    out = _pre(data)
    assert out["messages"][0]["content"] == "오늘 날씨 어때?"
    assert out["metadata"][MAPPING_KEY] == {}


def test_pre_call_embeddings_masked():
    data = {"model": "e", "input": "메일 a@b.com"}
    out = _pre(data, call_type="aembedding")
    assert "a@b.com" not in out["input"]
