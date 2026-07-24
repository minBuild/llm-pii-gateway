"""프롬프트 인젝션 휴리스틱 탐지 (THREAT_MODEL R2).

⚠️ 프롬프트 인젝션 탐지는 본질적으로 **미해결·적대적** 문제다. 이 모듈은 '차단'을
보장하지 않는다 — 알려진 공격 표현군을 점수화해 **플래깅**하는 방어심층 한 겹이다.

접근:
- 카테고리별 (패턴, 가중치) 목록으로 신호를 모은다. 강한 표지(예: "developer mode",
  "ignore previous instructions", 채팅 제어토큰)는 단독 플래그(2), 약한 표지(예: 역할설정
  동사 "act as")는 보강 필요(1). 점수 = 카테고리별 최댓값의 합(같은 카테고리 중복 가산 방지).
- 입력은 `normalize_for_detection` 로 정규화해 전각/제로폭 위장을 무력화한 뒤 매칭.
- 점수 임계는 호출자(정책)가 정한다 — 탐지기는 점수/카테고리만 반환.

한계(THREAT_MODEL R2 잔여, 과장 금지): 의역·신규 표현, KO/EN 외 언어, base64 등 인코딩
스머글링(단독은 약신호로만), 간접 인젝션(RAG/tool 출력), 트리거 없는 의미론적 공격은 못
잡는다. 또한 공격을 '설명·인용'하는 정상 요청(use vs mention)을 구분하지 못해 오탐이 날 수
있다 — 그래서 기본 정책은 `log_only`(관측 우선)이며, FP는 `tests/util/injection_eval.py`
벤치마크로 관리한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import normalize_for_detection

# 카테고리 → ((패턴, 가중치), ...). 가중치 2=단독 강신호, 1=보강 필요한 약신호.
# 점수는 카테고리별로 '발화한 패턴 중 최대 가중치'만 합산한다(한 카테고리 다중매치 부풀림 방지).
_PATTERNS: dict[str, tuple[tuple[re.Pattern[str], int], ...]] = {
    "OVERRIDE": (  # 지시 무효화
        (re.compile(r"(ignore|disregard|forget|override)\b.{0,30}?\b(previous|prior|earlier|above|all|your|the)\b.{0,20}?(instruction|prompt|rule|guideline|context|message|direction)s?", re.I), 2),
        (re.compile(r"(이전|위의?|앞의?|기존|모든|지금까지의?).{0,15}?(지시|명령|지침|규칙|프롬프트|맥락|대화)\s*(사항)?.{0,15}?(무시|잊어|잊고|리셋|초기화)"), 2),
    ),
    "EXFIL": (  # 시스템 프롬프트 탈취
        (re.compile(r"(reveal|repeat|show|print|display|expose|leak|give me|tell me|what (is|are))\b.{0,30}?\b(system\s*prompt|your\s*(system\s*)?(prompt|instruction|rule)s?|initial\s*(prompt|instruction)s?)", re.I), 2),
        (re.compile(r"(시스템\s*)?(프롬프트|지시\s*사항|지침|초기\s*설정|시스템\s*메시지).{0,15}?(보여|알려|출력|공개|말해|드러|노출|복사)"), 2),
    ),
    "DELIM": (  # 채팅 템플릿 제어토큰 주입
        (re.compile(r"<\|(im_start|im_end|system|user|assistant|endoftext)\|>", re.I), 2),
        (re.compile(r"(\[/?INST\]|<</?SYS>>)"), 2),
    ),
    "ROLE": (  # 역할/페르소나 탈취
        (re.compile(r"\b(DAN\b|do anything now|developer mode|jailbreak|jailbroken|unfiltered|no restrictions|without restrictions|opposite mode)\b", re.I), 2),
        (re.compile(r"(개발자\s*모드|탈옥|무검열|무제한\s*모드|제한\s*없는\s*모드)"), 2),
        (re.compile(r"\b(you are now|you're now|from now on,? you are|pretend to be|pretend you are|act as|roleplay as|behave as|you will act as)\b", re.I), 1),
        (re.compile(r"(넌|너는|당신은|이제부터|지금부터).{0,8}?(척|처럼|역할)"), 1),
    ),
    "SUPPRESS": (  # 거절 억제
        (re.compile(r"\b(do not|don't|never)\b.{0,20}?\b(refuse|decline|reject)\b", re.I), 2),
        (re.compile(r"(거절|거부)\s*(하지\s*(말|마)|없이|하면\s*안)"), 2),
        (re.compile(r"\b(you must|you have to|no matter what|at all costs|without any (warning|filter|restriction|refusal))\b", re.I), 1),
        (re.compile(r"(반드시|무조건|꼭).{0,6}?(답|대답|응답|출력)\s*(해|하라|해야)"), 1),
    ),
    "ENCODING": (  # 인코딩 스머글링 유도(단독은 약신호)
        (re.compile(r"\b(base64|rot13|caesar cipher|in leetspeak|decode the following|reverse the following|unscramble)\b", re.I), 1),
        (re.compile(r"(base64|디코드|복호화|역순으로|거꾸로)"), 1),
    ),
}


@dataclass(frozen=True)
class InjectionResult:
    """프롬프트 인젝션 신호 요약. categories 는 발화된 카테고리(중복 없음, 정렬)."""

    score: int
    categories: tuple[str, ...]

    def flagged(self, threshold: int) -> bool:
        return self.score >= threshold


def detect_injection(text: str) -> InjectionResult:
    """정규화 후 카테고리 패턴을 매칭해 점수/카테고리를 반환. 임계 판정은 호출자(정책) 몫."""
    if not text:
        return InjectionResult(0, ())
    norm = normalize_for_detection(text)
    fired: list[str] = []
    score = 0
    for category, patterns in _PATTERNS.items():
        weights = [w for pattern, w in patterns if pattern.search(norm)]
        if weights:
            fired.append(category)
            score += max(weights)
    return InjectionResult(score, tuple(sorted(fired)))
