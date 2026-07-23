"""L1 탐지 품질 측정 하니스 (B: 탐지 품질 튜닝).

어려운 한국어 엣지 케이스로 엔티티별 정밀도/재현율을 측정한다. 테스트(pass/fail)가 아니라
**측정 도구** — 약점을 찾아 정규식/규칙을 튜닝하는 루프에 쓴다.

    ./.venv/bin/python -m tests.util.eval
"""

from __future__ import annotations

from collections import Counter

from kpii.detectors import detect_l1
from kpii.engine import merge
from tests.util import gen

# (text, 기대 엔티티 집합). 엣지/오탐유도 위주.
HARD_CASES: list[tuple[str, set[str]]] = [
    # PHONE 엣지
    ("국제표기 +82 10-1234-5678 로 연락", {"PHONE"}),
    ("국가코드 +82-10-9876-5432 입니다", {"PHONE"}),
    ("서울 (02)123-4567 내선", {"PHONE"}),
    ("대표 02)987-6543", {"PHONE"}),
    ("점구분 010.5555.6666", {"PHONE"}),
    ("공백 010 5555 6666", {"PHONE"}),
    # RRN 엣지
    (f"무하이픈 {gen.gen_rrn(hyphen=False)}", {"RRN"}),
    (f"공백형 {gen.gen_rrn().replace('-', ' ')}", {"RRN"}),
    # CARD 엣지
    (f"무구분 카드 {gen.gen_card(hyphen=False)}", {"CARD"}),
    (f"19자리 카드 {gen.gen_card19()}", {"CARD"}),                 # B: 19자리 연속
    (f"19자리 그룹 {gen.gen_card19(grouped=True)}", {"CARD"}),      # B: 19자리 4-4-4-4-3
    ("13자리수열 1234567890128 참고", set()),                       # 13자리 Luhn유효라도 카드 아님(RRN/ISBN 충돌 회피)
    ("14자리수열 12345678901237 코드", set()),                      # 14자리 제외
    # EMAIL 엣지
    ("서브도메인 user.name+tag@mail.example.co.kr 로", {"EMAIL"}),
    # 혼합
    (f"주민 {gen.gen_rrn()} 폰 010-1111-2222", {"RRN", "PHONE"}),
    # 음성(오탐 유도)
    ("주문번호 20240315123456 배송중", set()),
    ("고객센터 1588-1234 문의", set()),          # 대표번호(개인 아님) — 미탐 허용
    ("버전 3.10.14 릴리스", set()),
    ("금액 1,250,000 원 청구", set()),
    (f"체크섬 틀린 카드 {gen.flip_last_digit(gen.gen_card(hyphen=False))}", set()),
    ("우편번호 06236 강남", set()),
    # PASSPORT (문맥 필수)
    ("여권 M12345678 소지", {"PASSPORT"}),
    ("여권번호 M123A4567 발급", {"PASSPORT"}),
    ("코드 M12345678 참조", set()),                       # 문맥 없음 → 미탐(정밀도)
    # BANK_ACCOUNT (문맥 필수)
    ("입금 계좌 123-456-789012 로", {"BANK_ACCOUNT"}),
    ("우리은행 1002-345-678901 이체", {"BANK_ACCOUNT"}),
    ("숫자열 123-456-789012 참고", set()),                 # 문맥 없음
    # DRIVER_LICENSE (문맥 필수)
    ("운전면허 11-23-123456-78 확인", {"DRIVER_LICENSE"}),
    ("번호 11-23-123456-78 기록", set()),                  # 문맥 없음
    # BRN (체크섬 필수)
    (f"사업자등록번호 {gen.gen_brn()} 조회", {"BRN"}),
    (f"무효 {gen.flip_last_digit(gen.gen_brn())} 등록", set()),
    # CREDENTIAL
    ("aws AKIAIOSFODNN7EXAMPLE 노출", {"CREDENTIAL"}),
    ("openai sk-proj-abcdefghijklmnopqrstuvwxyz01 확인", {"CREDENTIAL"}),
    ("구글키 AIza" + "A" * 35 + " 유출", {"CREDENTIAL"}),
    # 추가 음성(오탐 유도)
    ("IPv4 192.168.0.1 접속", set()),
    ("주문 2024-0315-0001 처리", set()),
    ("ISBN 978-89-12345-67-8 판매", set()),
]


def evaluate(cases):
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    misses: list[tuple[str, str]] = []
    falsepos: list[tuple[str, str]] = []
    for text, expected in cases:
        detected = {d.entity for d in merge(detect_l1(text))}
        for e in expected:
            if e in detected:
                tp[e] += 1
            else:
                fn[e] += 1
                misses.append((e, text))
        for e in detected - expected:
            fp[e] += 1
            falsepos.append((e, text))
    return tp, fp, fn, misses, falsepos


def report(cases=HARD_CASES) -> None:
    tp, fp, fn, misses, falsepos = evaluate(cases)
    entities = sorted(set(tp) | set(fp) | set(fn))
    print(f"{'entity':16}{'TP':>4}{'FP':>4}{'FN':>4}{'prec':>7}{'rec':>7}")
    for e in entities:
        prec = tp[e] / (tp[e] + fp[e]) if (tp[e] + fp[e]) else 1.0
        rec = tp[e] / (tp[e] + fn[e]) if (tp[e] + fn[e]) else 1.0
        print(f"{e:16}{tp[e]:>4}{fp[e]:>4}{fn[e]:>4}{prec:>7.2f}{rec:>7.2f}")
    if misses:
        print("\n미탐(FN):")
        for e, t in misses:
            print(f"  [{e}] {t!r}")
    if falsepos:
        print("\n오탐(FP):")
        for e, t in falsepos:
            print(f"  [{e}] {t!r}")


if __name__ == "__main__":
    report()
