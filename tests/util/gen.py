"""합성 PII 생성기 + 테스트 코퍼스 (DESIGN §9-4).

실존 인물/실제 번호는 절대 사용하지 않는다. 체크섬이 필요한 값은 모두 규칙에 맞춰
프로그램으로 생성한다. 체크섬 알고리즘은 kpii.validators 와 동일하지만, 테스트가
구현을 그대로 베끼지 않도록(독립 검증) 여기서 별도로 재구현한다.
"""

from __future__ import annotations

# ---------------- 체크섬 계산 (독립 재구현) ----------------


def _rrn_check(body12: str) -> int:
    ds = [int(c) for c in body12]
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    s = sum(d * w for d, w in zip(ds, weights))
    return (11 - (s % 11)) % 10


def _luhn_check_digit(base: str) -> int:
    for c in range(10):
        ds = [int(x) for x in base + str(c)]
        total = 0
        for i, d in enumerate(reversed(ds)):
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        if total % 10 == 0:
            return c
    return 0


def _brn_check(base9: str) -> int:
    ds = [int(c) for c in base9]
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(d * w for d, w in zip(ds, weights))
    s += (ds[8] * 5) // 10
    return (10 - (s % 10)) % 10


# ---------------- 생성기 ----------------


def gen_rrn(year: int = 1988, month: int = 3, day: int = 15, gender: int = 1,
            serial: str = "12345", hyphen: bool = True) -> str:
    body = f"{year % 100:02d}{month:02d}{day:02d}{gender}{serial}"
    full = body + str(_rrn_check(body))
    return f"{full[:6]}-{full[6:]}" if hyphen else full


def gen_card(base15: str = "453212345678901", hyphen: bool = True) -> str:
    n = base15 + str(_luhn_check_digit(base15))
    return f"{n[0:4]}-{n[4:8]}-{n[8:12]}-{n[12:16]}" if hyphen else n


def gen_brn(base9: str = "123456789") -> str:
    n = base9 + str(_brn_check(base9))
    return f"{n[0:3]}-{n[3:5]}-{n[5:10]}"


def flip_last_digit(s: str) -> str:
    """문자열의 마지막 숫자를 다른 값으로 바꿔 체크섬을 깬다(형식은 유지)."""
    for i in range(len(s) - 1, -1, -1):
        if s[i].isdigit():
            return s[:i] + str((int(s[i]) + 1) % 10) + s[i + 1 :]
    return s


# ---------------- 코퍼스 ----------------


def positives() -> list[tuple[str, str]]:
    """(text, 단일 기대 엔티티). text 는 해당 엔티티 하나만 포함하도록 구성."""
    return [
        (f"제 주민등록번호는 {gen_rrn()} 입니다.", "RRN"),
        (f"주민번호 {gen_rrn(hyphen=False)} 확인 바랍니다.", "RRN"),
        # 생년월일은 유효하지만 체크섬만 틀린 경우(2020+ 임의번호 모사)도 탐지되어야 함
        (f"임의번호 {flip_last_digit(gen_rrn())} 케이스", "RRN"),
        ("연락처 010-1234-5678 로 연락 주세요.", "PHONE"),
        ("전화 01098765432 입니다.", "PHONE"),
        ("사무실 02-123-4567 로 전화 주세요.", "PHONE"),
        ("이메일 hong@example.com 으로 보내주세요.", "EMAIL"),
        (f"카드번호 {gen_card()} 로 결제했습니다.", "CARD"),
        (f"카드 {gen_card(hyphen=False)} 승인", "CARD"),
        ("운전면허 11-23-123456-78 소지 중.", "DRIVER_LICENSE"),
        ("여권번호 M12345678 입니다.", "PASSPORT"),
        ("여권 M123A4567 발급 완료.", "PASSPORT"),
        ("입금 계좌 123-456-789012 로 보내주세요.", "BANK_ACCOUNT"),
        (f"사업자등록번호 {gen_brn()} 입니다.", "BRN"),
        ("api key: sk-abcdefghijklmnopqrstuvwxyz012345 노출됨", "CREDENTIAL"),
        ("AWS AKIAIOSFODNN7EXAMPLE 유출 주의", "CREDENTIAL"),
        ("토큰 ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 확인", "CREDENTIAL"),
    ]


def multi() -> list[tuple[str, frozenset[str]]]:
    """(text, 기대 엔티티 집합). 이름(홍길동)은 NER(Phase 4) 대상이라 L1에선 미탐지."""
    return [
        ("홍길동 010-1234-5678, hong@example.com 참고", frozenset({"PHONE", "EMAIL"})),
        (f"주민 {gen_rrn()} / 카드 {gen_card()}", frozenset({"RRN", "CARD"})),
    ]


def negatives() -> list[str]:
    """detect_l1 결과가 비어야 하는 오탐 유도 케이스."""
    return [
        "주문번호 2013132512345 확인",              # 13자리지만 월=13 → RRN 날짜 무효
        "행사일 20260722 진행 예정",                 # 8자리 날짜
        "송장번호 123456789012 배송중",              # 12자리, 운전/면허 문맥 없음 → DRIVER 아님
        "결제금액 1,234,567원 청구되었습니다",
        "버전 1.2.3-rc.4 릴리스 노트",
        f"결제 실패 카드 {flip_last_digit(gen_card())} 재시도",   # Luhn 실패 16자리
        "번호 123-456-789012 참고하세요",            # 계좌 형태지만 문맥 없음 → BANK 아님
        f"등록 {flip_last_digit(gen_brn())} 은 무효",           # BRN 체크섬 실패 + 문맥 없음
        "코드 M12345678 참조",                        # 여권 형태지만 문맥 없음 → PASSPORT 아님
        "식별자 11-23-123456-78 기록됨",             # 면허 형태지만 문맥 없음 → DRIVER 아님
    ]


if __name__ == "__main__":
    # 검토용 코퍼스 파일 생성: python -m tests.util.gen (repo 루트에서)
    import json
    import pathlib

    out = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "korean_pii_corpus.jsonl"
    rows: list[dict] = []
    for text, ent in positives():
        rows.append({"kind": "positive", "text": text, "expect": [ent]})
    for text, ents in multi():
        rows.append({"kind": "multi", "text": text, "expect": sorted(ents)})
    for text in negatives():
        rows.append({"kind": "negative", "text": text, "expect": []})
    out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(rows)} rows -> {out}")
