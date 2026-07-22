"""정책 로더/검증 테스트 (DESIGN §4.3)."""

import pathlib

import pytest

from kpii import Action, Policy

ROOT = pathlib.Path(__file__).resolve().parents[2]  # tests/unit/ → repo 루트


def test_load_default_yaml():
    pol = Policy.load(ROOT / "policies" / "default.yaml")
    assert pol.action_for("RRN") is Action.BLOCK
    assert pol.action_for("CREDENTIAL") is Action.BLOCK
    assert pol.action_for("PHONE") is Action.MASK
    assert pol.action_for("BRN") is Action.LOG_ONLY
    assert pol.action_for("UNKNOWN_XYZ") is Action.MASK   # 카탈로그 밖 → default
    assert pol.on_internal_error == "block"
    assert pol.ner.enabled is False


def test_invalid_action_raises():
    with pytest.raises(ValueError):
        Policy.from_dict({"entities": {"RRN": {"action": "nope"}}})


def test_missing_action_key_raises():
    with pytest.raises(ValueError):
        Policy.from_dict({"entities": {"RRN": {"foo": "bar"}}})


def test_invalid_on_internal_error_raises():
    with pytest.raises(ValueError):
        Policy.from_dict({"on_internal_error": "maybe"})


def test_invalid_ner_on_failure_raises():
    with pytest.raises(ValueError):
        Policy.from_dict({"ner": {"on_failure": "explode"}})
