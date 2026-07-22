"""마스킹/복원 테스트 (DESIGN §5)."""

from kpii import MaskingSession, merge
from kpii.detectors import detect_l1
from kpii.masking import PLACEHOLDER_RE
from tests.util import gen


def test_roundtrip_exact():
    # 픽스처의 모든 양성 케이스에서 mask→restore 왕복이 바이트 일치해야 한다
    for text, _ in gen.positives():
        dets = merge(detect_l1(text))
        s = MaskingSession()
        masked = s.mask(text, dets)
        assert s.restore(masked) == text


def test_same_value_same_placeholder():
    text = "메일은 a@b.com, 확인용도 a@b.com 재전송"
    s = MaskingSession()
    masked = s.mask(text, merge(detect_l1(text)))
    assert masked.count("[EMAIL_1]") == 2   # 동일 값 → 동일 플레이스홀더
    assert len(s.mapping) == 1


def test_multi_entity_offsets():
    text = "A 010-1234-5678 B hong@x.com C"
    s = MaskingSession()
    masked = s.mask(text, merge(detect_l1(text)))
    assert "010-1234-5678" not in masked
    assert "hong@x.com" not in masked
    assert s.restore(masked) == text


def test_placeholder_format():
    text = "폰 010-1234-5678 끝"
    s = MaskingSession()
    masked = s.mask(text, merge(detect_l1(text)))
    assert PLACEHOLDER_RE.findall(masked) == ["[PHONE_1]"]


def test_detection_repr_redacts_value():
    dets = detect_l1("메일 a@b.com")
    r = repr(dets[0])
    assert "redacted" in r
    assert "a@b.com" not in r
