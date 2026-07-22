"""Presidio 클라이언트 오프라인 테스트 (httpx MockTransport, Presidio 불필요)."""

import asyncio
import json

import pytest

pytest.importorskip("httpx")
import httpx  # noqa: E402

from kpii.detectors.presidio_client import PresidioClient  # noqa: E402
from kpii.types import NerUnavailable  # noqa: E402


def _client(handler) -> PresidioClient:
    ac = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PresidioClient("http://presidio:3000", client=ac)


def test_parses_person_and_location_ignores_others():
    text = "김민수 고객이 서울시 강남구로 이사"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["language"] == "ko"
        assert body["entities"] == ["PERSON", "LOCATION"]
        return httpx.Response(200, json=[
            {"entity_type": "PERSON", "start": 0, "end": 3, "score": 0.9},
            {"entity_type": "LOCATION", "start": 8, "end": 11, "score": 0.85},
            {"entity_type": "DATE_TIME", "start": 0, "end": 2, "score": 0.4},   # 무시
        ])

    dets = asyncio.run(_client(handler).detect(text))
    pairs = {(d.entity, d.value) for d in dets}
    assert ("PERSON", "김민수") in pairs
    assert ("LOCATION", "서울시") in pairs
    assert len(dets) == 2                     # DATE_TIME 무시됨
    assert all(d.source == "ner" for d in dets)


def test_http_error_raises_ner_unavailable():
    dets_handler = lambda req: httpx.Response(500)  # noqa: E731
    with pytest.raises(NerUnavailable):
        asyncio.run(_client(dets_handler).detect("김민수"))


def test_connect_error_raises_ner_unavailable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(NerUnavailable):
        asyncio.run(_client(handler).detect("김민수"))


def test_empty_text_skips_call():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=[])

    assert asyncio.run(_client(handler).detect("")) == []
    assert calls["n"] == 0                    # 빈 텍스트는 호출 안 함
