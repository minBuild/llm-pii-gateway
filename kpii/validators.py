"""정형 PII 체크섬/유효성 검증기 (DESIGN 부록 A). 표준 라이브러리만 사용."""

from __future__ import annotations

import datetime


def digits_only(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def luhn_valid(number: str) -> bool:
    """Luhn 체크섬 (부록 A.2). 카드번호 탐지 확정 조건."""
    ds = [int(c) for c in digits_only(number)]
    if len(ds) < 2:
        return False
    total = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2 == 1:  # 오른쪽에서 2, 4, ... 번째를 2배
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# 주민등록번호 성별코드 → 출생 세기 (부록 A.1 / §4.1 각주 1). 9·0(1800년대)은 제외.
_RRN_CENTURY = {1: 1900, 2: 1900, 3: 2000, 4: 2000, 5: 1900, 6: 1900, 7: 2000, 8: 2000}


def rrn_date_valid(number: str) -> bool:
    """RRN 앞 7자리(생년월일 + 성별코드)가 실제 과거 날짜인지. 탐지 확정 조건."""
    ds = digits_only(number)
    if len(ds) != 13:
        return False
    gender = int(ds[6])
    if gender not in _RRN_CENTURY:
        return False
    year = _RRN_CENTURY[gender] + int(ds[0:2])
    try:
        birth = datetime.date(year, int(ds[2:4]), int(ds[4:6]))
    except ValueError:
        return False
    return birth <= datetime.date.today()


def rrn_checksum_valid(number: str) -> bool:
    """RRN 체크섬 (부록 A.1).

    2020-10 이후 발급분엔 적용되지 않으므로, 통과 여부는 '탐지'가 아니라 '신뢰도'에만
    쓴다 (§4.1 각주 1). 탐지 확정은 rrn_date_valid 가 담당.
    """
    ds = [int(c) for c in digits_only(number)]
    if len(ds) != 13:
        return False
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    s = sum(d * w for d, w in zip(ds[:12], weights))
    check = (11 - (s % 11)) % 10
    return check == ds[12]


def brn_checksum_valid(number: str) -> bool:
    """사업자등록번호 체크섬 (부록 A.3)."""
    ds = [int(c) for c in digits_only(number)]
    if len(ds) != 10:
        return False
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(d * w for d, w in zip(ds[:9], weights))
    s += (ds[8] * 5) // 10
    check = (10 - (s % 10)) % 10
    return check == ds[9]
