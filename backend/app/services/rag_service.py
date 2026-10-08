from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from app.core.config import get_settings
from app.services.providers import GeminiMalformedResponseError, GeminiProvider, LLMProvider
from app.services.retrieval_service import RetrievalService, RetrievedChunk


class RAGService:
    def __init__(self, retrieval: RetrievalService, llm: LLMProvider | None = None) -> None:
        self.retrieval = retrieval
        self.llm = llm or GeminiProvider()

    async def answer(self, user_id: str, query: str, history: list[dict[str, str]], document_ids: list[str] | None = None) -> dict[str, Any]:
        if document_ids is not None and not document_ids:
            return {'answer': 'The information is not available in the documents.', 'citations': []}
        raw = await self.llm.generate(
            'Create exactly 3 concise search query variants and one broader step-back query for the user question. '
            'Return a JSON object with string fields queries (array of 3 strings) and step_back (string). '
            'Return JSON only. Question: ' + query
        )
        try:
            match = re.search(r'\{.*\}', raw, re.S)
            parsed = json.loads(match.group(0)) if match else None
            variants = parsed.get('queries') if isinstance(parsed, dict) else None
            variants = [item.strip() for item in variants if isinstance(item, str) and item.strip()] if isinstance(variants, list) else []
            step_back = parsed.get('step_back') if isinstance(parsed, dict) else None
            if len(variants) < 3 or not isinstance(step_back, str) or not step_back.strip():
                raise ValueError('required query variants missing')
            queries = [query, *variants[:4], step_back.strip()]
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise GeminiMalformedResponseError(
                operation='query_expansion', model=get_settings().gemini_model,
                message='Gemini returned malformed query expansion data.',
            ) from error
        ranked: dict[str, dict[str, Any]] = {}
        for q in dict.fromkeys(queries):
            results = await self.retrieval.retrieve(user_id, q, top_k=8, document_ids=document_ids)
            for rank, item in enumerate(results, start=1):
                key = str(item.chunk.id)
                slot = ranked.setdefault(key, {'item': item, 'rrf': 0.0})
                slot['rrf'] += 1.0 / (60 + rank)
        ordered = sorted(ranked.values(), key=lambda slot: slot['rrf'], reverse=True)[:8]
        if not ordered:
            return {'answer': 'The information is not available in the documents.', 'citations': []}
        context = []
        for slot in ordered:
            item: RetrievedChunk = slot['item']
            context.append(f"[chunk_id={item.chunk.id}; document_id={item.document.id}; filename={item.document.filename}; page={item.chunk.page_number or 'unknown'}]\n{item.chunk.content[:2200]}")
        history_text = '\n'.join(f"{m['role']}: {m['content'][:1500]}" for m in history[-8:])
        prompt = ('Answer using only the supplied document context. If it does not support an answer, say the information is not available in the documents. '
                  'Return only the answer text.\nCONVERSATION HISTORY:\n' + history_text + '\nQUESTION:\n' + query + '\nDOCUMENT CONTEXT:\n' + '\n\n'.join(context))
        answer = await self.llm.generate(prompt)
        if not answer.strip():
            raise GeminiMalformedResponseError(
                operation='generation', model=get_settings().gemini_model,
                message='Gemini returned an empty grounded answer.',
            )
        citations = [{'chunk_id': str(slot['item'].chunk.id), 'document_id': slot['item'].document.id,
                      'filename': slot['item'].document.filename, 'page_number': slot['item'].chunk.page_number,
                      'relevance_score': float(slot['rrf'])} for slot in ordered]
        return {'answer': answer, 'citations': citations}
