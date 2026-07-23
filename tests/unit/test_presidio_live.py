"""실제 Presidio(in-process) + 한국어 모델로 L2 매핑 검증 (HTTP/도커 불필요).

nlp_conf 매핑(PS→PERSON, LC→LOCATION)이 실제 적용되고, 결과 필드가 PresidioClient 가
기대하는 형태(entity_type/start/end/score)인지 확인한다.

설치되어 있을 때만 실행(무거운 옵션 의존):
    pip install presidio-analyzer
    pip install https://github.com/explosion/spacy-models/releases/download/\
ko_core_news_sm-3.8.0/ko_core_news_sm-3.8.0-py3-none-any.whl
없으면 skip.
"""

import pytest

pytest.importorskip("presidio_analyzer")
spacy = pytest.importorskip("spacy")

try:
    spacy.load("ko_core_news_sm")
except OSError:
    pytest.skip("ko_core_news_sm 모델 미설치", allow_module_level=True)

from presidio_analyzer import AnalyzerEngine  # noqa: E402
from presidio_analyzer.nlp_engine import NlpEngineProvider  # noqa: E402

# presidio/nlp_conf.yaml 과 동일한 매핑 (검증용은 sm 모델; 운영은 lg — 라벨셋 동일)
_CONF = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "ko", "model_name": "ko_core_news_sm"}],
    "ner_model_configuration": {
        "model_to_presidio_entity_mapping": {"PS": "PERSON", "LC": "LOCATION", "OG": "ORGANIZATION"},
        "labels_to_ignore": ["O"],
    },
}


def test_presidio_ko_maps_person_and_location():
    engine = NlpEngineProvider(nlp_configuration=_CONF).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=engine, supported_languages=["ko"])
    text = "김민수 고객이 서울시 강남구로 이사했습니다"

    results = analyzer.analyze(text=text, language="ko", entities=["PERSON", "LOCATION"])
    got = {(r.entity_type, text[r.start : r.end]) for r in results}
    assert ("PERSON", "김민수") in got
    assert ("LOCATION", "서울시") in got

    # PresidioClient 파싱이 의존하는 필드 형태 확인
    for r in results:
        assert isinstance(r.entity_type, str)
        assert 0 <= r.start < r.end <= len(text)
        assert 0.0 <= r.score <= 1.0
