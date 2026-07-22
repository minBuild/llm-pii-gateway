"""fake upstream(FastAPI) 오프라인 검증 — in-process ASGI, 서버/도커 불필요.

fastapi/httpx 미설치 시 skip.
"""

import asyncio
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import httpx  # noqa: E402

from tests.fake_upstream.app import app  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_health():
    async def go():
        async with _client() as c:
            return await c.get("/health")

    r = _run(go())
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_chat_echo_and_last_request_stored():
    body = {"model": "mock-model", "messages": [{"role": "user", "content": "ECHO:안녕 [PHONE_1]"}]}

    async def go():
        async with _client() as c:
            r = await c.post("/v1/chat/completions", json=body)
            last = await c.get("/_last_request")
            return r, last

    r, last = _run(go())
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "안녕 [PHONE_1]"    # ECHO 모드
    assert last.json()["messages"][0]["content"].startswith("ECHO:")            # 수신 바디 저장


def test_chat_stream_reassembles():
    body = {"model": "mock-model", "stream": True,
            "messages": [{"role": "user", "content": "ECHO:abcdefg"}]}

    async def go():
        lines = []
        async with _client() as c:
            async with c.stream("POST", "/v1/chat/completions?chunk=3", json=body) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and "[DONE]" not in line:
                        lines.append(line)
        return lines

    text = ""
    for line in _run(go()):
        delta = json.loads(line[len("data: ") :])["choices"][0]["delta"]
        text += delta.get("content", "")
    assert text == "abcdefg"    # 청크(3자)로 쪼갠 걸 이어붙이면 원문


def test_embeddings_returns_vectors():
    body = {"model": "mock-model", "input": ["a", "b"]}

    async def go():
        async with _client() as c:
            return await c.post("/v1/embeddings", json=body)

    r = _run(go())
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2
