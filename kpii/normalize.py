"""입력 정규화 — 탐지 회피(evasion) 방지 전처리 (THREAT_MODEL R1).

공격자는 전각 숫자(０１０)·원형 숫자(①)·제로폭 문자·소프트하이픈 등으로 정규식 탐지를
피하려 한다. 탐지 **직전에** 다음을 적용해 이런 변형을 표준형으로 접는다:

1. 보이지 않는/방향 제어 문자 제거(제로폭·BOM·소프트하이픈·BIDI 제어).
2. Unicode NFKC 정규화 — 전각→반각, 원형숫자(①)→1, 호환형을 표준형으로.

정합성: 게이트웨이는 이 정규화된 문자열로 **탐지·마스킹·전달을 일관되게** 수행한다
(openai_gateway._iter_scan_fields). 따라서 스팬 오프셋이 어긋나지 않는다.
한글 완성형·영문·이메일은 NFKC 에서 변하지 않는다(검증: tests/unit/test_normalize.py).

한계(정규화로는 못 막는 것 — THREAT_MODEL R1 잔여): 숫자를 낱자 공백으로 쪼갠 표기
("0 1 0 …"), 한글 낱말 표기("공일공"), base64/인코딩, 스크립트 혼용 호모글리프(키릴 등).
이들은 재현율↔정밀도 트레이드오프가 커서 별도 대응 대상이다.
"""

from __future__ import annotations

import unicodedata

# 폭 0 / 보이지 않는 / 방향 제어(BIDI) 문자 — 문자 사이에 끼워 넣어 탐지를 피하는 데 쓰인다.
_INVISIBLE = dict.fromkeys(
    map(
        ord,
        [
            "​",  # ZERO WIDTH SPACE
            "‌",  # ZERO WIDTH NON-JOINER
            "‍",  # ZERO WIDTH JOINER
            "⁠",  # WORD JOINER
            "﻿",  # ZERO WIDTH NO-BREAK SPACE (BOM)
            "­",  # SOFT HYPHEN
            "᠎",  # MONGOLIAN VOWEL SEPARATOR
            "‪", "‫", "‬", "‭", "‮",  # BIDI embedding/override
            "⁦", "⁧", "⁨", "⁩",            # BIDI isolates
        ],
    )
)


def normalize_for_detection(text: str) -> str:
    """탐지 회피 방지 전처리: 보이지 않는 문자 제거 후 NFKC 정규화."""
    if not text:
        return text
    return unicodedata.normalize("NFKC", text.translate(_INVISIBLE))
