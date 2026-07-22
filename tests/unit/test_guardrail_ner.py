"""guardrail NER 경로 오프라인 테스트 (ner_client 주입, 실제 Presidio/litellm proxy 불필요)."""

import asyncio
import pathlib

import pytest

pytest.importorskip("litellm")

import yaml  # noqa: E402
from litellm.proxy._types import ProxyException  # noqa: E402

from custom_guardrails.kpii_guardrail import MAPPING_KEY, KoreanPIIGuardrail  # noqa: E402
from kpii.types import Detection, NerUnavailable  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


class _MockNer:
    def __init__(self, fail: bool = False):
        self._fail = fail

    async def detect(self, text: str):
        if self._fail:
            raise NerUnavailable("down")
        return [Detection("PERSON", 0, 3, text[0:3], 0.9, "ner")] if text.startswith("김민수") else []


def test_guardrail_masks_person_via_ner():
    g = KoreanPIIGuardrail(
        policy_path=str(ROOT / "policies" / "with-ner.yaml"),
        guardrail_name="kpii",
        ner_client=_MockNer(),
    )
    data = {"model": "m", "messages": [{"role": "user", "content": "김민수 고객 문의"}]}
    out = asyncio.run(g.async_pre_call_hook(None, None, data, "acompletion"))
    assert "김민수" not in out["messages"][0]["content"]
    assert "[PERSON_1]" in out["messages"][0]["content"]
    assert "[PERSON_1]" in out["metadata"][MAPPING_KEY]


def test_guardrail_ner_down_degrades(caplog):
    # with-ner.yaml 은 on_failure: degrade → NER 죽어도 통과(L1만), 예외 없음
    g = KoreanPIIGuardrail(
        policy_path=str(ROOT / "policies" / "with-ner.yaml"),
        guardrail_name="kpii",
        ner_client=_MockNer(fail=True),
    )
    data = {"model": "m", "messages": [{"role": "user", "content": "김민수 010-1234-5678"}]}
    out = asyncio.run(g.async_pre_call_hook(None, None, data, "acompletion"))
    # NER 실패 → PERSON 마스킹 못하지만 L1(PHONE)은 마스킹, 요청은 통과
    assert "[PHONE_1]" in out["messages"][0]["content"]


def test_guardrail_ner_down_block_policy_returns_503(tmp_path):
    policy_file = tmp_path / "with-ner-block.yaml"
    policy_file.write_text(
        yaml.safe_dump({
            "version": 1,
            "default_action": "mask",
            "entities": {"PERSON": {"action": "mask"}},
            "on_internal_error": "block",
            "ner": {"enabled": True, "on_failure": "block"},
        }),
        encoding="utf-8",
    )
    g = KoreanPIIGuardrail(
        policy_path=str(policy_file), guardrail_name="kpii", ner_client=_MockNer(fail=True)
    )
    data = {"model": "m", "messages": [{"role": "user", "content": "김민수"}]}
    with pytest.raises(ProxyException) as ei:
        asyncio.run(g.async_pre_call_hook(None, None, data, "acompletion"))
    assert str(ei.value.code) == "503"
    assert "ner_unavailable" in ei.value.message
