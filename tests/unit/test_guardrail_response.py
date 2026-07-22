"""응답 복원 훅 오프라인 테스트 (Phase 3, DESIGN §5.2·§5.3).

litellm 응답 객체 대신 동일 구조의 mock(SimpleNamespace)으로 훅의 순회/복원 배선을 검증.
스트림 복원 코어(StreamRestorer)는 test_stream.py 에서 별도 검증됨.
litellm 미설치 시 skip.
"""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("litellm")

from custom_guardrails.kpii_guardrail import MAPPING_KEY, KoreanPIIGuardrail  # noqa: E402

MAPPING = {"[PHONE_1]": "010-1234-5678"}


def _guard() -> KoreanPIIGuardrail:
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    return KoreanPIIGuardrail(policy_path=str(root / "policies" / "default.yaml"), guardrail_name="kpii")


def _resp(content, tool_args=None):
    msg = SimpleNamespace(content=content, tool_calls=None)
    if tool_args is not None:
        msg.tool_calls = [SimpleNamespace(function=SimpleNamespace(arguments=tool_args))]
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


async def _agen(chunks):
    for c in chunks:
        yield c


def _chunk(content=None, finish=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish)])


# ---------------- 비스트리밍 ----------------


def test_success_hook_restores_content():
    g = _guard()
    data = {"metadata": {MAPPING_KEY: MAPPING}}
    resp = _resp("고객님 [PHONE_1] 로 안내드립니다")
    out = asyncio.run(g.async_post_call_success_hook(data, None, resp))
    assert out.choices[0].message.content == "고객님 010-1234-5678 로 안내드립니다"


def test_success_hook_restores_tool_arguments():
    g = _guard()
    data = {"metadata": {MAPPING_KEY: MAPPING}}
    resp = _resp("확인했습니다", tool_args='{"phone": "[PHONE_1]"}')
    out = asyncio.run(g.async_post_call_success_hook(data, None, resp))
    assert out.choices[0].message.tool_calls[0].function.arguments == '{"phone": "010-1234-5678"}'


def test_success_hook_no_mapping_is_noop():
    g = _guard()
    resp = _resp("[PHONE_1] 그대로")
    out = asyncio.run(g.async_post_call_success_hook({"metadata": {}}, None, resp))
    assert out.choices[0].message.content == "[PHONE_1] 그대로"


# ---------------- 스트리밍 ----------------


def _collect(gen_coro_factory) -> str:
    async def go():
        parts = []
        async for c in gen_coro_factory():
            d = c.choices[0].delta.content
            if d:
                parts.append(d)
        return "".join(parts)

    return asyncio.run(go())


def test_streaming_hook_restores_across_chunk_boundary():
    g = _guard()
    req = {"metadata": {MAPPING_KEY: MAPPING}}
    text = "[PHONE_1] 고객님"
    parts = [text[i : i + 3] for i in range(0, len(text), 3)]     # 3자 분할 → 플레이스홀더가 쪼개짐
    chunks = [_chunk(content=p) for p in parts] + [_chunk(content="", finish="stop")]
    out = _collect(lambda: g.async_post_call_streaming_iterator_hook(None, _agen(chunks), req))
    assert out == "010-1234-5678 고객님"


def test_streaming_hook_passthrough_when_no_mapping():
    g = _guard()
    req = {"metadata": {}}
    chunks = [_chunk(content="[PHONE_1]"), _chunk(content=" 끝", finish="stop")]
    out = _collect(lambda: g.async_post_call_streaming_iterator_hook(None, _agen(chunks), req))
    assert out == "[PHONE_1] 끝"        # 매핑 없으면 복원 안 함, 무손상


def test_streaming_hook_unmapped_placeholder_passthrough():
    g = _guard()
    req = {"metadata": {MAPPING_KEY: MAPPING}}
    chunks = [_chunk(content="[EMAIL_9] 와 [PHONE_1]"), _chunk(content="", finish="stop")]
    out = _collect(lambda: g.async_post_call_streaming_iterator_hook(None, _agen(chunks), req))
    assert "[EMAIL_9]" in out          # 매핑에 없는 건 그대로
    assert "010-1234-5678" in out      # 매핑에 있는 건 복원
