"""입력 정규화(탐지 회피 방지) 테스트 — THREAT_MODEL R1.

정규화 단위 동작 + 회피 벡터 방어 + 게이트웨이 배선(정규화→마스킹) + 잔여 한계 고정.
"""

from __future__ import annotations

from pathlib import Path

from kpii.detectors import detect_l1
from kpii.engine import merge
from kpii.masking import MaskingSession
from kpii.normalize import normalize_for_detection as N
from kpii.openai_gateway import process_request
from kpii.policy import Policy
from tests.util import adversarial as adv
from tests.util import gen

ROOT = Path(__file__).resolve().parents[2]
POLICY = Policy.load(ROOT / "policies" / "default.yaml")   # PHONE=mask, RRN=block


def _ents(text: str) -> set[str]:
    return {d.entity for d in merge(detect_l1(text))}


# ---------------- normalize 단위 동작 ----------------


def test_strips_zero_width():
    assert N("010​-1234​-5678") == "010-1234-5678"


def test_strips_bidi_and_soft_hyphen():
    # 소프트하이픈(U+00AD) + BIDI override(U+202E) 제거
    assert N("A­B‮C") == "ABC"


def test_folds_fullwidth():
    assert N("０１０－１２３４－５６７８") == "010-1234-5678"


def test_folds_circled_digits():
    assert N("①②③") == "123"


def test_preserves_korean_and_email():
    s = "홍길동 hong@example.com 계좌"
    assert N(s) == s


# ---------------- 회피 벡터가 정규화로 방어되는가 ----------------


def test_fullwidth_bypasses_raw_but_caught_after_normalize():
    payload = f"연락처 {adv.fullwidth('010-1234-5678')} 참고"
    assert "PHONE" not in _ents(payload)      # raw 로는 뚫림(회피 성공)
    assert "PHONE" in _ents(N(payload))       # 정규화 후 탐지 복구


def test_zerowidth_circled_softhyphen_caught_after_normalize():
    for fn in (adv.zero_width, adv.circled, adv.soft_hyphen):
        payload = f"연락처 {fn('010-1234-5678')} 참고"
        assert "PHONE" not in _ents(payload), f"{fn.__name__}: raw 에서 이미 탐지?"
        assert "PHONE" in _ents(N(payload)), f"{fn.__name__}: 정규화 후에도 미탐"


# ---------------- 게이트웨이 배선: 정규화가 마스킹/차단까지 이어지는가 ----------------


def test_gateway_masks_fullwidth_phone():
    fw = adv.fullwidth("010-1234-5678")
    body = {"messages": [{"role": "user", "content": f"내 번호 {fw} 임"}]}
    res = process_request(body, POLICY, MaskingSession())
    out = body["messages"][0]["content"]
    assert not res.blocked
    assert res.detections.get("PHONE", 0) >= 1
    assert "[PHONE_" in out          # 마스킹 적용됨
    assert fw not in out             # 원문(전각) 미유출
    assert "０" not in out            # 전각 숫자가 남지 않음(정규화됨)


def test_gateway_blocks_fullwidth_rrn():
    # RRN 은 default 정책상 block — 전각으로 위장해도 정규화 후 차단되어야 한다.
    body = {"messages": [{"role": "user", "content": f"주민번호 {adv.fullwidth(gen.gen_rrn())}"}]}
    res = process_request(body, POLICY, MaskingSession())
    assert res.blocked
    assert "RRN" in res.block_entities


# ---------------- 잔여 한계(R1)를 명시적으로 고정 ----------------


def test_residual_spaced_and_spelled_still_bypass():
    """정규화로는 못 막는 잔여 벡터 — 알려진 한계를 테스트로 고정(회귀 시 인지)."""
    for fn in (adv.space_out, adv.spell_ko):
        payload = f"연락처 {fn('01012345678')} 참고"
        assert "PHONE" not in _ents(N(payload)), f"{fn.__name__}: 잔여 가정이 바뀜(재검토)"
