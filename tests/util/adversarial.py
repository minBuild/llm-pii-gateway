"""적대적 회피(evasion) 측정 하니스 (THREAT_MODEL R1).

공격자가 탐지기를 우회하려고 쓰는 변형을 PII 문자열에 적용해, **정규화 전/후** 탐지율을
잰다. 목적은 두 가지:
  1) 어떤 회피 벡터가 실제로 뚫리는지 수치로 드러낸다(과장·은폐 없이).
  2) `kpii.normalize` 로 막히는 벡터와, 못 막는 잔여 벡터를 구분한다.

측정 도구(테스트 아님):  ./.venv/bin/python -m tests.util.adversarial
"""

from __future__ import annotations

from collections.abc import Callable

from kpii.detectors import detect_l1
from kpii.engine import merge
from kpii.normalize import normalize_for_detection
from tests.util import gen

# ---------------- 회피 변형 ----------------

_FW = {ord(c): chr(ord(c) + 0xFEE0) for c in "0123456789"}  # ASCII 숫자 → 전각
_FW[ord("-")] = "－"                                         # 전각 하이픈
_CIRCLED = {str(i): chr(0x2460 + i - 1) for i in range(1, 10)} | {"0": "⓪"}
_KO = dict(zip("0123456789", "공일이삼사오육칠팔구"))


def fullwidth(s: str) -> str:
    return s.translate(_FW)


def circled(s: str) -> str:
    return "".join(_CIRCLED.get(c, c) for c in s)


def zero_width(s: str) -> str:
    return "​".join(s)          # 매 문자 사이 ZERO WIDTH SPACE


def soft_hyphen(s: str) -> str:
    return "­".join(s)          # 매 문자 사이 SOFT HYPHEN


def space_out(s: str) -> str:
    return " ".join(s)               # 매 문자 사이 일반 공백


def spell_ko(s: str) -> str:
    return "".join(_KO.get(c, c) for c in s)   # 010 → 공일공


VECTORS: list[tuple[str, Callable[[str], str], str]] = [
    ("전각(fullwidth)",   fullwidth,   "normalize"),   # 기대: 정규화로 방어
    ("원형숫자(circled)", circled,     "normalize"),
    ("제로폭(ZWSP)",      zero_width,  "normalize"),
    ("소프트하이픈",       soft_hyphen, "normalize"),
    ("공백분리",           space_out,   "residual"),    # 기대: 잔여(못 막음)
    ("한글표기(공일공)",   spell_ko,    "residual"),
]

# 회피 대상 기준 PII — 변형이 의미 있는 숫자형 위주
_BASES: list[tuple[str, str]] = [
    ("PHONE", "010-1234-5678"),
    ("RRN", gen.gen_rrn()),
    ("CARD", gen.gen_card()),
]


def _detect(text: str) -> set[str]:
    return {d.entity for d in merge(detect_l1(text))}


def report() -> None:
    print(f"{'vector':22}{'raw':>8}{'normalized':>13}{'expect':>12}")
    for name, fn, expect in VECTORS:
        raw_hit = norm_hit = 0
        for ent, base in _BASES:
            payload = f"연락처 {fn(base)} 참고"
            if ent in _detect(payload):
                raw_hit += 1
            if ent in _detect(normalize_for_detection(payload)):
                norm_hit += 1
        n = len(_BASES)
        print(f"{name:22}{f'{raw_hit}/{n}':>8}{f'{norm_hit}/{n}':>13}{expect:>12}")
    print("\nraw=정규화 없음 탐지수 / normalized=정규화 후 탐지수 (높을수록 방어됨).")
    print("expect=normalize: 정규화로 막혀야 함 / residual: 정규화로는 못 막는 잔여(R1).")


if __name__ == "__main__":
    report()
