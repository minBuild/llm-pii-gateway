"""스트리밍 복원 테스트: 청크 경계에 걸친 플레이스홀더 (DESIGN §5.3)."""

from kpii import MaskingSession, merge
from kpii.detectors import detect_l1


def _chunks(s: str, size: int) -> list[str]:
    return [s[i : i + size] for i in range(0, len(s), size)]


def _mask(text: str) -> tuple[MaskingSession, str]:
    s = MaskingSession()
    return s, s.mask(text, merge(detect_l1(text)))


def test_stream_restore_various_chunk_sizes():
    text = "안내: 010-1234-5678 / hong@example.com 확인 바랍니다"
    s, masked = _mask(text)
    # 플레이스홀더를 1~3글자 단위로 쪼개도 최종 복원 결과가 원문과 일치해야 한다
    for size in (1, 2, 3, 5, 7, 999):
        r = s.stream_restorer()
        out = "".join(r.push(c) for c in _chunks(masked, size)) + r.flush()
        assert out == text, f"size={size}: {out!r}"


def test_stream_passthrough_when_no_mapping():
    s = MaskingSession()  # 매핑 없음 → 버퍼링 없이 통과
    r = s.stream_restorer()
    parts = ["플레이스홀더 ", "아닌 [NOT", "APLACEHOLDER] 그대로"]
    out = "".join(r.push(p) for p in parts) + r.flush()
    assert out == "".join(parts)


def test_stream_unknown_placeholder_passthrough():
    s, _ = _mask("폰 010-1234-5678")     # 매핑에 [PHONE_1] 존재
    r = s.stream_restorer()
    text = "값 [UNKNOWN_9] 는 그대로, [PHONE_1] 는 복원"
    out = "".join(r.push(c) for c in _chunks(text, 3)) + r.flush()
    assert "[UNKNOWN_9]" in out          # 매핑에 없으면 그대로
    assert "[PHONE_1]" not in out        # 매핑에 있으면 복원됨
    assert "010-1234-5678" in out


def test_stream_trailing_incomplete_prefix():
    s, _ = _mask("폰 010-1234-5678")
    r = s.stream_restorer()
    out = r.push("문장 끝 미완성 [PHO") + r.flush()
    assert out == "문장 끝 미완성 [PHO"   # 완성 안 된 접두어는 원문 그대로 방출
