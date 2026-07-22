"""L1 탐지: 정규식 + 체크섬 (DESIGN §4.1, 부록 B). 인프로세스, 항상 동작.

부록 B는 초안이며 오탐(false positive)을 줄이는 방향으로 다듬었다. 주요 조정:
- DRIVER_LICENSE: 체크섬이 없어 12자리 숫자열과 충돌하므로 문맥 키워드(면허/운전) 필수로 변경.
- BANK_ACCOUNT: 문맥 키워드에서 흔한 일반어와 겹치는 은행명(우리/하나/기업 등)은 제외하고
  거래/계좌 관련어와 식별력 높은 은행 토큰만 사용.
- RRN/CARD/BRN: 각각 생년월일/Luhn/체크섬 게이트를 통과해야 탐지 확정.
"""

from __future__ import annotations

import re

from ..types import Detection
from ..validators import (
    brn_checksum_valid,
    digits_only,
    luhn_valid,
    rrn_checksum_valid,
    rrn_date_valid,
)

# --- 패턴 (숫자 연속 오매치 방지를 위해 (?<!\d)/(?!\d) 경계 사용) ---
_RRN = re.compile(r"(?<!\d)\d{6}[-\s·.]?[1-8]\d{6}(?!\d)")
_MOBILE = re.compile(r"(?<!\d)01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
_LANDLINE = re.compile(
    r"(?<!\d)0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70)[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD = re.compile(
    r"(?<!\d)(?:\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}|\d{4}[-\s]?\d{6}[-\s]?\d{5})(?!\d)"
)
_DRIVER = re.compile(r"(?<!\d)(?:1[1-9]|2[0-8])[-\s]?\d{2}[-\s]?\d{6}[-\s]?\d{2}(?!\d)")
_PASSPORT = re.compile(
    r"(?<![A-Za-z0-9])(?:[MSRODG]\d{8}|[MSRODG]\d{3}[A-Z]\d{4})(?![A-Za-z0-9])"
)
_BANK = re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,8}(?!\d)")
_BRN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)")
_CREDENTIAL = (
    re.compile(r"(?<![A-Za-z0-9])sk-(?:ant-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])ghp_[A-Za-z0-9]{36}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])xox[bpoas]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN(?: RSA| EC| OPENSSH)? PRIVATE KEY-----"),
)

# --- 문맥 필수 엔티티의 키워드 (§4.1 각주 2, 오탐 감소 목적으로 조정) ---
_CTX_PASSPORT = ("여권", "passport")
_CTX_DRIVER = ("면허", "운전")
_CTX_BANK = (
    "계좌", "입금", "이체", "송금", "은행", "예금", "출금",
    "카카오뱅크", "케이뱅크", "토스", "새마을금고", "우체국",
)
_CTX_WINDOW = 30


def _has_context(text: str, start: int, end: int, keywords, window: int = _CTX_WINDOW) -> bool:
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    haystack = (text[lo:start] + " " + text[end:hi]).lower()
    return any(k.lower() in haystack for k in keywords)


def detect_l1(text: str) -> list[Detection]:
    """텍스트에서 L1 엔티티를 모두 탐지. 겹침 정리는 engine.merge 가 담당."""
    out: list[Detection] = []

    # RRN — 생년월일 게이트 필수, 체크섬은 신뢰도만
    for m in _RRN.finditer(text):
        d = digits_only(m.group())
        if len(d) != 13 or not rrn_date_valid(d):
            continue
        conf = 1.0 if rrn_checksum_valid(d) else 0.8
        out.append(Detection("RRN", m.start(), m.end(), m.group(), conf, "regex"))

    # CARD — Luhn 필수
    for m in _CARD.finditer(text):
        if not luhn_valid(m.group()):
            continue
        out.append(Detection("CARD", m.start(), m.end(), m.group(), 1.0, "regex"))

    # PHONE — 모바일 + 유선
    for rx in (_MOBILE, _LANDLINE):
        for m in rx.finditer(text):
            out.append(Detection("PHONE", m.start(), m.end(), m.group(), 0.9, "regex"))

    # EMAIL
    for m in _EMAIL.finditer(text):
        out.append(Detection("EMAIL", m.start(), m.end(), m.group(), 0.98, "regex"))

    # DRIVER_LICENSE — 문맥 필수 (부록 B에서 조정)
    for m in _DRIVER.finditer(text):
        if _has_context(text, m.start(), m.end(), _CTX_DRIVER):
            out.append(Detection("DRIVER_LICENSE", m.start(), m.end(), m.group(), 0.75, "regex"))

    # PASSPORT — 문맥 필수
    for m in _PASSPORT.finditer(text):
        if _has_context(text, m.start(), m.end(), _CTX_PASSPORT):
            out.append(Detection("PASSPORT", m.start(), m.end(), m.group(), 0.7, "regex"))

    # BANK_ACCOUNT — 문맥 필수
    for m in _BANK.finditer(text):
        if _has_context(text, m.start(), m.end(), _CTX_BANK):
            out.append(Detection("BANK_ACCOUNT", m.start(), m.end(), m.group(), 0.7, "regex"))

    # BRN — 체크섬 필수
    for m in _BRN.finditer(text):
        if brn_checksum_valid(m.group()):
            out.append(Detection("BRN", m.start(), m.end(), m.group(), 1.0, "regex"))

    # CREDENTIAL — 키/토큰/개인키
    for rx in _CREDENTIAL:
        for m in rx.finditer(text):
            out.append(Detection("CREDENTIAL", m.start(), m.end(), m.group(), 1.0, "regex"))

    return out
