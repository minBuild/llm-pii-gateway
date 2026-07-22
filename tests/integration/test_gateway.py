"""통합테스트 — 실행 중인 게이트웨이 대상 (DESIGN Phase 2 DoD, 요청 방향).

전제: 로컬에서 통합 스택 기동 후 실행.
    make up-test          # docker compose (litellm + postgres + fake-upstream)
    make test-integration # 이 파일
    make down-test

게이트웨이가 안 떠 있으면 전체 skip. 이 환경(compose 미가용)에선 skip 되며,
compose 가능한 로컬에서 검증한다.
"""

import json
import os

import pytest

pytest.importorskip("httpx")
import httpx  # noqa: E402

from tests.util import gen  # noqa: E402

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:4000")
UPSTREAM = os.environ.get("FAKE_UPSTREAM_URL", "http://localhost:9000")
KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-master-CHANGE-ME")
HEADERS = {"Authorization": f"Bearer {KEY}"}


def _gateway_up() -> bool:
    try:
        return httpx.get(f"{GATEWAY}/health/liveliness", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _gateway_up(), reason="게이트웨이 미기동 (make up-test 필요)"),
]


def _chat(content: str, model: str = "mock-model", **kw):
    body = {"model": model, "messages": [{"role": "user", "content": content}], **kw}
    return httpx.post(f"{GATEWAY}/v1/chat/completions", json=body, headers=HEADERS, timeout=30)


def _last_upstream() -> dict:
    return httpx.get(f"{UPSTREAM}/_last_request", timeout=5).json()


def test_phone_masked_before_upstream():
    r = _chat("연락처 010-1234-5678 로 연락 주세요")
    assert r.status_code == 200
    sent = _last_upstream()["messages"][0]["content"]
    assert "010-1234-5678" not in sent
    assert "[PHONE_1]" in sent


def test_rrn_request_blocked():
    rrn = gen.gen_rrn()
    r = _chat(f"제 주민번호는 {rrn} 입니다")
    assert r.status_code == 400
    assert "pii_blocked" in r.text
    assert rrn not in r.text                      # 응답에 원문 미유출


def test_no_pii_passthrough_unchanged():
    r = _chat("오늘 서울 날씨 알려줘")
    assert r.status_code == 200
    assert _last_upstream()["messages"][0]["content"] == "오늘 서울 날씨 알려줘"


def test_system_message_masked():
    body = {
        "model": "mock-model",
        "messages": [
            {"role": "system", "content": "담당자 hong@example.com 로 문의"},
            {"role": "user", "content": "안내 부탁"},
        ],
    }
    r = httpx.post(f"{GATEWAY}/v1/chat/completions", json=body, headers=HEADERS, timeout=30)
    assert r.status_code == 200
    sent = _last_upstream()
    assert "hong@example.com" not in sent["messages"][0]["content"]


def test_embeddings_input_masked():
    r = httpx.post(
        f"{GATEWAY}/v1/embeddings",
        json={"model": "mock-model", "input": "메일 a@b.com"},
        headers=HEADERS, timeout=30,
    )
    assert r.status_code == 200
    inp = _last_upstream().get("input")
    haystack = inp if isinstance(inp, str) else " ".join(inp)
    assert "a@b.com" not in haystack


def test_log_only_brn_passthrough():
    brn = gen.gen_brn()
    r = _chat(f"사업자등록번호 {brn} 조회 부탁")
    assert r.status_code == 200
    assert brn in _last_upstream()["messages"][0]["content"]    # LOG_ONLY → 원문 유지


# ---------------- Phase 3: 응답 복원 ----------------


def test_response_restored_nonstreaming():
    phone = "010-1234-5678"
    r = _chat(f"ECHO:내 번호 {phone} 입니다")     # 업스트림이 마스킹된 텍스트를 에코
    assert r.status_code == 200
    content = r.json()["choices"][0]["message"]["content"]
    assert phone in content                        # 클라이언트는 원문을 본다(복원됨)
    assert "[PHONE_" not in content
    sent = _last_upstream()["messages"][-1]["content"]
    assert phone not in sent and "[PHONE_1]" in sent   # 업스트림엔 마스킹된 채로 도달


def test_response_restored_streaming():
    phone = "010-9876-5432"
    body = {"model": "mock-model", "stream": True,
            "messages": [{"role": "user", "content": f"ECHO:연락처 {phone}"}]}
    text = ""
    with httpx.stream("POST", f"{GATEWAY}/v1/chat/completions",
                      json=body, headers=HEADERS, timeout=30) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data: ") and "[DONE]" not in line:
                delta = json.loads(line[len("data: ") :])["choices"][0].get("delta", {})
                text += delta.get("content") or ""
    assert phone in text and "[PHONE_" not in text    # 스트리밍 청크 재조립 후 원문 복원


# ---------------- Phase 4: NER(L2) 이름/주소 ----------------
# NER 스택(presidio + with-ner 정책)이 떠 있을 때만. 기본 스택에선 skip:
#   docker compose ... --profile ner up -d --build   (+ guardrail 정책 with-ner.yaml)
#   KPII_NER_E2E=1 pytest -m integration

_NER_E2E = os.environ.get("KPII_NER_E2E") == "1"


@pytest.mark.skipif(not _NER_E2E, reason="NER E2E 아님 (KPII_NER_E2E=1 + presidio/with-ner 스택 필요)")
def test_ner_masks_person_and_location():
    r = _chat("김민수 고객이 서울시 강남구로 이사했습니다")
    assert r.status_code == 200
    sent = _last_upstream()["messages"][0]["content"]
    assert "김민수" not in sent and "[PERSON_1]" in sent
    assert "서울시" not in sent and "[LOCATION_1]" in sent
