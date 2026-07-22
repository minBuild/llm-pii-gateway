# Presidio Analyzer + 한국어 spaCy 모델 사이드카 (DESIGN §6.6, Phase 4).
# analyzer 만 사용 — 마스킹은 kpii 엔진이 하므로 anonymizer 불필요.
#
# VERIFY(로컬): 아래는 시작점이다. 이 환경에서 실행/검증하지 못했으므로 빌드 시 확인할 것:
#  1) 베이스 이미지 태그를 특정 버전으로 고정(:latest → mcr.microsoft.com/presidio-analyzer:<ver>).
#  2) analyzer 가 NLP 설정 파일을 읽는 경로/환경변수(이미지 버전마다 다를 수 있음).
#  3) ko_core_news_lg 의 실제 NER 라벨셋(nlp.pipe_labels) → nlp_conf.yaml 매핑과 일치하는지.
FROM mcr.microsoft.com/presidio-analyzer:latest

# 한국어 모델 설치(설치 이미지의 spaCy 버전과 호환되는 버전을 spacy 가 선택)
RUN python -m spacy download ko_core_news_lg

COPY nlp_conf.yaml /app/nlp_conf.yaml
# analyzer 가 이 설정을 읽도록 지정(이미지 버전에 맞는 방식으로 조정 — VERIFY).
ENV ANALYZER_CONF_FILE=/app/nlp_conf.yaml
