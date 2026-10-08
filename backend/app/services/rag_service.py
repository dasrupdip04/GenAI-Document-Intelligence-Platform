from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import get_settings
from app.services.providers import (
    GeminiMalformedResponseError,
    GeminiProvider,
    LLMProvider,
)
from app.services.retrieval_service import (
    RetrievalService,
    RetrievedChunk,
)


class RAGService:
    def __init__(
        self,
        retrieval: RetrievalService,
        llm: LLMProvider | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.llm = llm or GeminiProvider()

    async def _expand_query(
        self,
        query: str,
    ) -> list[str]:
        """
        Generate:
        - exactly 3 alternative retrieval queries
        - exactly 1 broader step-back query

        This is ONE Gemini generation request.
        """

        raw = await self.llm.generate(
            (
                "Create exactly 3 concise search query variants "
                "and one broader step-back query for the user question. "
                "Return a JSON object with string fields "
                '"queries" (array of 3 strings) and '
                '"step_back" (string). '
                "Return JSON only.\n"
                "Question: "
                + query
            )
        )

        try:
            match = re.search(
                r"\{.*\}",
                raw,
                re.S,
            )

            parsed = (
                json.loads(match.group(0))
                if match
                else None
            )

            variants = (
                parsed.get("queries")
                if isinstance(parsed, dict)
                else None
            )

            variants = (
                [
                    item.strip()
                    for item in variants
                    if isinstance(item, str)
                    and item.strip()
                ]
                if isinstance(variants, list)
                else []
            )

            step_back = (
                parsed.get("step_back")
                if isinstance(parsed, dict)
                else None
            )

            if (
                len(variants) < 3
                or not isinstance(step_back, str)
                or not step_back.strip()
            ):
                raise ValueError(
                    "required query variants missing"
                )

            # Keep exactly three variants.
            variants = variants[:3]

            queries = [
                query.strip(),
                *variants,
                step_back.strip(),
            ]

            # Remove duplicates while preserving order.
            return list(dict.fromkeys(queries))

        except (
            AttributeError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise GeminiMalformedResponseError(
                operation="query_expansion",
                model=get_settings().gemini_model,
                message=(
                    "Gemini returned malformed query "
                    "expansion data."
                ),
            ) from error

    async def answer(
        self,
        user_id: str,
        query: str,
        history: list[dict[str, str]],
        document_ids: list[str] | None = None,
    ) -> dict[str, Any]:

        if document_ids is not None and not document_ids:
            return {
                "answer": (
                    "The information is not available "
                    "in the documents."
                ),
                "citations": [],
            }

        # ---------------------------------------------------------
        # STEP 1: Query expansion
        # ---------------------------------------------------------
        #
        # ONE Gemini generation call.
        #
        # Result:
        #   original query
        #   + 3 variants
        #   + 1 step-back query
        #
        queries = await self._expand_query(query)

        # ---------------------------------------------------------
        # STEP 2: Batched embedding + retrieval
        # ---------------------------------------------------------
        #
        # ONE Gemini embedding API call for ALL queries.
        #
        # Retrieval itself performs pgvector searches.
        #
        retrieval_results = (
            await self.retrieval.retrieve_many(
                user_id=user_id,
                queries=queries,
                top_k=8,
                document_ids=document_ids,
            )
        )

        # ---------------------------------------------------------
        # STEP 3: Reciprocal Rank Fusion
        # ---------------------------------------------------------

        ranked: dict[str, dict[str, Any]] = {}

        for results in retrieval_results:
            for rank, item in enumerate(
                results,
                start=1,
            ):
                key = str(item.chunk.id)

                slot = ranked.setdefault(
                    key,
                    {
                        "item": item,
                        "rrf": 0.0,
                    },
                )

                slot["rrf"] += 1.0 / (60 + rank)

        ordered = sorted(
            ranked.values(),
            key=lambda slot: slot["rrf"],
            reverse=True,
        )[:8]

        if not ordered:
            return {
                "answer": (
                    "The information is not available "
                    "in the documents."
                ),
                "citations": [],
            }

        # ---------------------------------------------------------
        # STEP 4: Build grounded context
        # ---------------------------------------------------------

        context: list[str] = []

        for slot in ordered:
            item: RetrievedChunk = slot["item"]

            context.append(
                (
                    f"[chunk_id={item.chunk.id}; "
                    f"document_id={item.document.id}; "
                    f"filename={item.document.filename}; "
                    f"page={item.chunk.page_number or 'unknown'}]\n"
                    f"{item.chunk.content[:2200]}"
                )
            )

        history_text = "\n".join(
            (
                f"{message['role']}: "
                f"{message['content'][:1500]}"
            )
            for message in history[-8:]
        )

        # ---------------------------------------------------------
        # STEP 5: Final grounded generation
        # ---------------------------------------------------------

        prompt = (
            "Answer using only the supplied document context. "
            "If it does not support an answer, say the "
            "information is not available in the documents.\n"
            "Return only the answer text.\n\n"
            "CONVERSATION HISTORY:\n"
            f"{history_text}\n\n"
            "QUESTION:\n"
            f"{query}\n\n"
            "DOCUMENT CONTEXT:\n"
            + "\n\n".join(context)
        )

        # ONE Gemini generation call.
        #
        # The provider itself may perform ONE retry only if
        # Gemini returns a transient 5xx.
        answer = await self.llm.generate(prompt)

        if not answer.strip():
            raise GeminiMalformedResponseError(
                operation="generation",
                model=get_settings().gemini_model,
                message=(
                    "Gemini returned an empty grounded answer."
                ),
            )

        # ---------------------------------------------------------
        # STEP 6: Citations
        # ---------------------------------------------------------

        citations = [
            {
                "chunk_id": str(slot["item"].chunk.id),
                "document_id": slot["item"].document.id,
                "filename": slot["item"].document.filename,
                "page_number": slot["item"].chunk.page_number,
                "relevance_score": float(slot["rrf"]),
            }
            for slot in ordered
        ]

        return {
            "answer": answer,
            "citations": citations,
        }