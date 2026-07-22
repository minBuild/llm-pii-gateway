"""체크섬/유효성 검증기 테스트 (DESIGN 부록 A)."""

from kpii.validators import (
    brn_checksum_valid,
    luhn_valid,
    rrn_checksum_valid,
    rrn_date_valid,
)
from tests.util import gen


def test_luhn():
    assert luhn_valid(gen.gen_card(hyphen=False))
    assert not luhn_valid(gen.flip_last_digit(gen.gen_card(hyphen=False)))


def test_rrn_checksum():
    assert rrn_checksum_valid(gen.gen_rrn(hyphen=False))
    assert not rrn_checksum_valid(gen.flip_last_digit(gen.gen_rrn(hyphen=False)))


def test_rrn_date():
    assert rrn_date_valid(gen.gen_rrn(hyphen=False))
    assert not rrn_date_valid("2013132512345")          # 월=13 → 무효
    assert not rrn_date_valid(gen.gen_rrn(year=2099, gender=3, hyphen=False))  # 미래 출생 → 무효
    assert not rrn_date_valid("123456")                 # 길이 부족


def test_brn_checksum():
    assert brn_checksum_valid(gen.gen_brn())
    assert not brn_checksum_valid(gen.flip_last_digit(gen.gen_brn()))
