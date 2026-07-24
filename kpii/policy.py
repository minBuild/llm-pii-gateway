"""정책 파일 로더/검증 (DESIGN §4.3). PyYAML 필요."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .types import Action

_VALID_ON_ERROR = {"block", "allow"}
_VALID_NER_FAILURE = {"degrade", "block"}
_VALID_INJECTION_ACTION = {"block", "log_only"}


@dataclass(frozen=True)
class NerConfig:
    enabled: bool = False
    api_base: str = "http://presidio-analyzer:3000"
    timeout_ms: int = 300
    on_failure: str = "degrade"


@dataclass(frozen=True)
class InjectionConfig:
    """프롬프트 인젝션 휴리스틱 정책. action=log_only 가 기본(관측 우선, FP 피해 최소화)."""

    enabled: bool = False
    action: str = "log_only"   # block | log_only
    threshold: int = 2         # injection.detect_injection 점수 임계


@dataclass(frozen=True)
class Policy:
    version: int
    default_action: Action
    entities: dict[str, Action]
    on_internal_error: str  # "block" | "allow"
    ner: NerConfig
    injection: InjectionConfig = InjectionConfig()
    max_scan_chars: int = 0   # 필드당 최대 스캔 길이(0=무제한). 초과 시 요청 차단(413). THREAT_MODEL R4

    def action_for(self, entity: str) -> Action:
        return self.entities.get(entity, self.default_action)

    @classmethod
    def load(cls, path: str | Path) -> "Policy":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Policy":
        version = int(data.get("version", 1))
        default_action = _parse_action(data.get("default_action", "mask"), "default_action")

        entities: dict[str, Action] = {}
        for name, spec in (data.get("entities") or {}).items():
            if not isinstance(spec, dict) or "action" not in spec:
                raise ValueError(f"entities.{name}: 'action' 키가 필요합니다")
            entities[name] = _parse_action(spec["action"], f"entities.{name}.action")

        on_internal_error = str(data.get("on_internal_error", "block"))
        if on_internal_error not in _VALID_ON_ERROR:
            raise ValueError(
                f"on_internal_error 는 {sorted(_VALID_ON_ERROR)} 중 하나여야 합니다: {on_internal_error!r}"
            )

        ner_raw = data.get("ner") or {}
        on_failure = str(ner_raw.get("on_failure", "degrade"))
        if on_failure not in _VALID_NER_FAILURE:
            raise ValueError(
                f"ner.on_failure 는 {sorted(_VALID_NER_FAILURE)} 중 하나여야 합니다: {on_failure!r}"
            )
        ner = NerConfig(
            enabled=bool(ner_raw.get("enabled", False)),
            api_base=str(ner_raw.get("api_base", "http://presidio-analyzer:3000")),
            timeout_ms=int(ner_raw.get("timeout_ms", 300)),
            on_failure=on_failure,
        )

        inj_raw = data.get("injection") or {}
        inj_action = str(inj_raw.get("action", "log_only")).lower()
        if inj_action not in _VALID_INJECTION_ACTION:
            raise ValueError(
                f"injection.action 는 {sorted(_VALID_INJECTION_ACTION)} 중 하나여야 합니다: {inj_action!r}"
            )
        injection = InjectionConfig(
            enabled=bool(inj_raw.get("enabled", False)),
            action=inj_action,
            threshold=int(inj_raw.get("threshold", 2)),
        )

        max_scan_chars = int(data.get("max_scan_chars", 0))
        if max_scan_chars < 0:
            raise ValueError(f"max_scan_chars 는 0 이상이어야 합니다: {max_scan_chars}")
        return cls(
            version, default_action, entities, on_internal_error, ner, injection, max_scan_chars
        )


def _parse_action(value: object, where: str) -> Action:
    try:
        return Action(str(value).lower())
    except ValueError:
        valid = [a.value for a in Action]
        raise ValueError(f"{where}: 알 수 없는 action {value!r} (가능: {valid})") from None
