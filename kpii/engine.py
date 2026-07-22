"""탐지 통합 진입점: L1(+L2) 실행, 스팬 병합, 정책 기반 분류 (DESIGN §6.2)."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from .detectors import detect_l1
from .policy import Policy
from .types import Action, Detection, NerUnavailable

_logger = logging.getLogger("kpii")


def merge(detections: Iterable[Detection]) -> list[Detection]:
    """겹치는 스팬 정리: (1) 더 긴 것 우선, (2) 길이 같으면 L1(regex) 우선 (§6.2)."""
    order = sorted(
        detections,
        key=lambda d: (-(d.end - d.start), 0 if d.source == "regex" else 1, d.start),
    )
    chosen: list[Detection] = []
    for d in order:
        if any(d.start < c.end and c.start < d.end for c in chosen):
            continue  # 이미 선택된 것과 겹침 → 스킵
        chosen.append(d)
    chosen.sort(key=lambda d: d.start)
    return chosen


def scan(text: str, policy: Policy) -> list[Detection]:
    """L1(정규식+체크섬)만 실행하고 병합. NER(L2) 포함은 scan_async."""
    dets = [d for d in detect_l1(text) if policy.action_for(d.entity) is not Action.OFF]
    return merge(dets)


async def scan_async(text: str, policy: Policy, ner_client=None) -> list[Detection]:
    """L1 + (정책상 NER 활성 시) L2 를 병합.

    ner_client 는 async detect(text)->list[Detection] 제공(Phase 4, PresidioClient).
    NER 실패(NerUnavailable) 시 정책 ner.on_failure 에 따라:
      - "block"   → 예외 전파(어댑터가 503 차단)
      - "degrade" → 경고 로그 후 L1 결과만으로 진행
    """
    dets: list[Detection] = detect_l1(text)
    if policy.ner.enabled and ner_client is not None:
        try:
            dets += await ner_client.detect(text)
        except NerUnavailable:
            if policy.ner.on_failure == "block":
                raise
            _logger.warning("NER 사이드카 불가 — L1 결과만으로 degrade 진행")
            # TODO(Phase 5): kpii_ner_failures_total 메트릭 증가
    dets = [d for d in dets if policy.action_for(d.entity) is not Action.OFF]
    return merge(dets)


def plan(
    detections: Iterable[Detection], policy: Policy
) -> tuple[list[Detection], list[Detection], list[Detection]]:
    """정책에 따라 (block, mask, log_only) 로 분류."""
    blocks: list[Detection] = []
    masks: list[Detection] = []
    logs: list[Detection] = []
    for d in detections:
        action = policy.action_for(d.entity)
        if action is Action.BLOCK:
            blocks.append(d)
        elif action is Action.MASK:
            masks.append(d)
        elif action is Action.LOG_ONLY:
            logs.append(d)
    return blocks, masks, logs
