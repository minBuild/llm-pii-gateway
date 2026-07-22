"""공통 타입 정의. 이 모듈은 표준 라이브러리 외 의존이 없다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# 플레이스홀더/정책에서 공통으로 쓰는 엔티티 이름. 여기가 단일 소스.
ENTITY_NAMES: tuple[str, ...] = (
    "RRN",
    "CARD",
    "PHONE",
    "EMAIL",
    "DRIVER_LICENSE",
    "PASSPORT",
    "BANK_ACCOUNT",
    "BRN",
    "CREDENTIAL",
    "PERSON",
    "LOCATION",
)


class Action(str, Enum):
    """엔티티별 처리 액션 (DESIGN §4.2)."""

    BLOCK = "block"
    MASK = "mask"
    LOG_ONLY = "log_only"
    OFF = "off"


@dataclass(frozen=True, repr=False)
class Detection:
    """탐지된 PII 스팬 하나.

    주의: `value`에는 PII 원문이 들어있다. __repr__ 에서 원문을 노출하지 않도록
    직접 재정의한다(로그/트레이스백 유출 방지, DESIGN §6.2·§9-3).
    """

    entity: str
    start: int
    end: int
    value: str
    confidence: float
    source: str  # "regex" | "ner"

    @property
    def length(self) -> int:
        return self.end - self.start

    def __repr__(self) -> str:  # 원문(value) 대신 길이만 노출
        return (
            f"Detection(entity={self.entity!r}, start={self.start}, end={self.end}, "
            f"value=<redacted len={len(self.value)}>, "
            f"confidence={self.confidence}, source={self.source!r})"
        )
