"""가역 마스킹 엔진 (DESIGN §5).

매핑에는 PII 원문이 들어있으므로 요청 스코프 인메모리로만 다루고, 로그/저장소/메트릭에
남기지 않는다 (D4).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .types import ENTITY_NAMES, Detection

# 긴 이름이 먼저 매칭되도록 정렬 (DRIVER_LICENSE, BANK_ACCOUNT 등)
_NAME_ALT = "|".join(sorted(ENTITY_NAMES, key=len, reverse=True))
PLACEHOLDER_RE = re.compile(r"\[(?:" + _NAME_ALT + r")_\d{1,3}\]")

# 가장 긴 플레이스홀더 "[DRIVER_LICENSE_999]" = 20자. 여유 있게 24.
MAX_PLACEHOLDER_LEN = 24

# '[' 이후 문자열이 플레이스홀더의 접두어가 될 수 있는지 (스트리밍 보류 판단, §5.3)
_POTENTIAL_PREFIX_RE = re.compile(r"^\[[A-Z_]*\d{0,3}\]?$")


class MaskingSession:
    """요청당 하나. 플레이스홀더 발급/치환/복원과 매핑을 보유."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._value_to_ph: dict[tuple[str, str], str] = {}
        self._ph_to_value: dict[str, str] = {}

    def _placeholder_for(self, entity: str, value: str) -> str:
        key = (entity, value)
        cached = self._value_to_ph.get(key)
        if cached is not None:
            return cached  # 동일 원문 → 동일 플레이스홀더 (§5.1)
        n = self._counters.get(entity, 0) + 1
        self._counters[entity] = n
        ph = f"[{entity}_{n}]"
        self._value_to_ph[key] = ph
        self._ph_to_value[ph] = value
        return ph

    def mask(self, text: str, detections: Iterable[Detection]) -> str:
        """detections 의 오프셋은 text 기준. 오른쪽부터 치환해 앞쪽 오프셋을 보존."""
        for d in sorted(detections, key=lambda x: x.start, reverse=True):
            ph = self._placeholder_for(d.entity, d.value)
            text = text[: d.start] + ph + text[d.end :]
        return text

    def restore(self, text: str) -> str:
        return PLACEHOLDER_RE.sub(
            lambda m: self._ph_to_value.get(m.group(0), m.group(0)), text
        )

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._ph_to_value)

    def stream_restorer(self) -> "StreamRestorer":
        return StreamRestorer(self._ph_to_value)


def restore(text: str, mapping: dict[str, str]) -> str:
    """플레이스홀더를 매핑으로 복원(세션 불필요). 매핑에 없는 토큰은 그대로 둔다."""
    if not mapping:
        return text
    return PLACEHOLDER_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)


def _is_potential_prefix(s: str) -> bool:
    return bool(_POTENTIAL_PREFIX_RE.match(s))


class StreamRestorer:
    """SSE 청크 경계에 걸친 플레이스홀더를 슬라이딩 버퍼로 복원 (§5.3).

    매핑이 비어 있으면 버퍼링 없이 그대로 통과(지연 0).
    """

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping
        self._buffer = ""
        self._passthrough = not mapping

    def push(self, text: str) -> str:
        if self._passthrough:
            return text
        self._buffer += text
        out: list[str] = []
        while True:
            i = self._buffer.find("[")
            if i == -1:  # '[' 없음 → 전부 안전
                out.append(self._buffer)
                self._buffer = ""
                break
            out.append(self._buffer[:i])
            self._buffer = self._buffer[i:]
            m = PLACEHOLDER_RE.match(self._buffer)
            if m:  # 완성된 플레이스홀더
                token = m.group(0)
                out.append(self._mapping.get(token, token))
                self._buffer = self._buffer[len(token) :]
                continue
            if _is_potential_prefix(self._buffer) and len(self._buffer) <= MAX_PLACEHOLDER_LEN:
                break  # 미완성 가능성 → 다음 청크 대기
            out.append(self._buffer[0])  # 플레이스홀더 아님 → '[' 하나 방출
            self._buffer = self._buffer[1:]
        return "".join(out)

    def flush(self) -> str:
        """스트림 종료 시 남은 버퍼 방출 (미완성 접두어는 원문 그대로)."""
        remaining, self._buffer = self._buffer, ""
        return remaining
