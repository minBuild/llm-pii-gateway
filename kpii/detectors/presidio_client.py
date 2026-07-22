"""L2 탐지: Presidio Analyzer 사이드카 HTTP 클라이언트 (DESIGN §6.6, Phase 4).

이름/주소 같은 비정형 PII 를 Presidio(+한국어 spaCy)로 탐지한다. 게이트웨이와 별도
프로세스(사이드카)라 HTTP(비동기)로 호출하고, 실패는 NerUnavailable 로 올려 engine 이
정책(ner.on_failure)에 따라 degrade/block 하게 한다.

httpx 는 [ner]/[dev] extra 로만 필요 — 이 모듈은 NER 활성 시에만 import 된다.
"""

from __future__ import annotations

import httpx

from ..types import Detection, NerUnavailable

# Presidio entity_type → kpii 엔티티. 그 외 타입(DATE_TIME 등)은 무시한다.
_ENTITY_MAP = {"PERSON": "PERSON", "LOCATION": "LOCATION"}


class PresidioClient:
    def __init__(
        self,
        api_base: str,
        timeout_ms: int = 300,
        language: str = "ko",
        entities: tuple[str, ...] = ("PERSON", "LOCATION"),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = api_base.rstrip("/") + "/analyze"
        self._language = language
        self._entities = list(entities)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_ms / 1000)

    async def detect(self, text: str) -> list[Detection]:
        if not text:
            return []
        try:
            resp = await self._client.post(
                self._url,
                json={"text": text, "language": self._language, "entities": self._entities},
            )
            resp.raise_for_status()
            results = resp.json()
        except (httpx.HTTPError, ValueError) as exc:   # 타임아웃/연결/HTTP상태/JSON 오류
            raise NerUnavailable(str(exc)) from exc

        out: list[Detection] = []
        for r in results or []:
            entity = _ENTITY_MAP.get(r.get("entity_type"))
            if entity is None:
                continue
            start, end = int(r["start"]), int(r["end"])
            out.append(
                Detection(entity, start, end, text[start:end], float(r.get("score", 0.5)), "ner")
            )
        return out

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
