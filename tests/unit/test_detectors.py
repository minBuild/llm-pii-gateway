"""L1 탐지 테스트: 픽스처 코퍼스 전건 (DESIGN Phase 1 DoD)."""

import pytest

from kpii import merge
from kpii.detectors import detect_l1
from tests.util import gen


@pytest.mark.parametrize("text,entity", gen.positives())
def test_positive_detected(text, entity):
    ents = {d.entity for d in merge(detect_l1(text))}
    assert ents == {entity}, f"기대 {{{entity}}}, 실제 {ents}"


@pytest.mark.parametrize("text", gen.negatives())
def test_negative_not_detected(text):
    dets = detect_l1(text)
    assert dets == [], f"오탐: {[(d.entity, d.value) for d in dets]}"


@pytest.mark.parametrize("text,entities", gen.multi())
def test_multi_detected(text, entities):
    ents = {d.entity for d in merge(detect_l1(text))}
    assert ents == set(entities)
