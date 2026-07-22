"""OpenAI 호환 가짜 업스트림 (DESIGN Phase 2). 통합테스트에서 litellm 이 라우팅.

- POST /v1/chat/completions: 수신 바디를 메모리에 저장. 마지막 user 텍스트가 'ECHO:'로
  시작하면 그 뒤를 응답 텍스트로 반환(Phase 3 복원 테스트용). stream=true 면 chunk 크기
  (기본 3자, ?chunk= 또는 CHUNK_SIZE)로 쪼개 SSE 전송.
- POST /v1/embeddings: 수신 바디 저장 + 더미 벡터 반환.
- GET /_last_request: 마지막 수신 바디 조회. GET /health: 헬스체크.
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
_state: dict[str, object] = {"body": None}


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _last_user_text(body: dict) -> str:
    for msg in reversed(body.get("messages") or []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        return part.get("text", "")
    return ""


def _response_text(body: dict) -> str:
    text = _last_user_text(body)
    if text.startswith("ECHO:"):
        return text[len("ECHO:") :].lstrip()
    return "안녕하세요, 무엇을 도와드릴까요?"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/_last_request")
def last_request() -> JSONResponse:
    return JSONResponse(_state["body"] or {})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    _state["body"] = body
    model = body.get("model", "mock-model")
    text = _response_text(body)

    if body.get("stream"):
        size = int(os.environ.get("CHUNK_SIZE", request.query_params.get("chunk", "3")))

        def stream():
            yield _sse({"id": "chatcmpl-fake", "object": "chat.completion.chunk", "model": model,
                        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
            for i in range(0, len(text), size):
                yield _sse({"id": "chatcmpl-fake", "object": "chat.completion.chunk", "model": model,
                            "choices": [{"index": 0, "delta": {"content": text[i : i + size]},
                                         "finish_reason": None}]})
            yield _sse({"id": "chatcmpl-fake", "object": "chat.completion.chunk", "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return JSONResponse({
        "id": "chatcmpl-fake", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    body = await request.json()
    _state["body"] = body
    inp = body.get("input")
    n = len(inp) if isinstance(inp, list) else 1
    return JSONResponse({
        "object": "list", "model": body.get("model", "mock-model"),
        "data": [{"object": "embedding", "index": i, "embedding": [0.0, 0.0, 0.0]} for i in range(n)],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    })
