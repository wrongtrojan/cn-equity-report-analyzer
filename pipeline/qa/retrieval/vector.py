from __future__ import annotations

from pipeline.db import connect, to_pgvector
from sentence_transformers import SentenceTransformer

from ..config import QUERY_EMBED_MODEL, VECTOR_TOP_K
from ..schemas import EvidenceItem
class VectorRetriever:
    _model: SentenceTransformer | None = None

    def __init__(self, top_k: int = VECTOR_TOP_K) -> None:
        self.top_k = top_k

    @classmethod
    def model(cls) -> SentenceTransformer:
        if cls._model is None:
            cls._model = SentenceTransformer(QUERY_EMBED_MODEL)
        return cls._model

    def retrieve(
        self,
        report_id: int,
        query_text: str,
        *,
        section_keys: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[EvidenceItem]:
        if not query_text.strip():
            return []

        limit = top_k if top_k is not None else self.top_k
        vec = self.model().encode(query_text, normalize_embeddings=True)
        vec_str = to_pgvector(vec.tolist())
        fetch_limit = limit * 4 if section_keys else limit * 2
        preferred = {k for k in (section_keys or []) if k}

        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT section_key, page_num, chunk_index, content, (embedding <=> %s::vector) AS dist
                FROM text_chunks
                WHERE report_id = %s
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_str, report_id, vec_str, fetch_limit),
            )
            rows = cur.fetchall()

        evidence: list[EvidenceItem] = []
        for section_key, page_num, chunk_index, content, dist in rows:
            score = max(0.0, 1.0 - float(dist))
            if preferred and section_key in preferred:
                score = min(1.0, score * 1.15)
            evidence.append(
                EvidenceItem(
                    source_type="text_chunk",
                    content=content,
                    section_key=section_key,
                    page_num=page_num,
                    score=score,
                    metadata={"chunk_index": chunk_index, "distance": float(dist)},
                )
            )

        evidence.sort(key=lambda x: (-x.score, x.metadata.get("chunk_index", 0)))
        return evidence[:limit]


