"""스팬 병합·스캔·정책 분류 테스트 (DESIGN §6.2)."""

from kpii import Detection, Policy, merge, plan, scan
from tests.util import gen


def _pol(**ent: str) -> Policy:
    entities = {k: {"action": v} for k, v in ent.items()}
    return Policy.from_dict(
        {
            "version": 1,
            "default_action": "mask",
            "entities": entities,
            "on_internal_error": "block",
            "ner": {"enabled": False},
        }
    )


def test_merge_longer_wins():
    # 같은 시작, 길이 다른 두 스팬이 겹치면 더 긴 것만 남는다
    short = Detection("DRIVER_LICENSE", 0, 12, "x" * 12, 0.75, "regex")
    longer = Detection("RRN", 0, 13, "y" * 13, 1.0, "regex")
    out = merge([short, longer])
    assert [d.entity for d in out] == ["RRN"]


def test_merge_keeps_disjoint():
    a = Detection("PHONE", 0, 5, "aaaaa", 0.9, "regex")
    b = Detection("EMAIL", 10, 20, "b" * 10, 0.98, "regex")
    out = merge([b, a])
    assert [d.entity for d in out] == ["PHONE", "EMAIL"]  # 시작 순 정렬


def test_scan_off_entity_filtered():
    pol = _pol(PHONE="off")
    ents = {d.entity for d in scan("연락처 010-1234-5678 메일 a@b.com", pol)}
    assert "PHONE" not in ents
    assert "EMAIL" in ents


def test_plan_classifies_by_policy():
    pol = _pol(RRN="block", PHONE="mask", BRN="log_only")
    text = f"주민 {gen.gen_rrn()} 폰 010-1234-5678 사업자 {gen.gen_brn()}"
    blocks, masks, logs = plan(scan(text, pol), pol)
    assert {d.entity for d in blocks} == {"RRN"}
    assert {d.entity for d in masks} == {"PHONE"}
    assert {d.entity for d in logs} == {"BRN"}
