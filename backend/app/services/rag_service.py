from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from app.services.providers import GeminiProvider, LLMProvider
from app.services.retrieval_service import RetrievalService, RetrievedChunk


class RAGService:
    def __init__(self, retrieval: RetrievalService, llm: LLMProvider | None = None) -> None:
        self.retrieval = retrieval
        self.llm = llm or GeminiProvider()

    async def answer(self, user_id: str, query: str, history: list[dict[str, str]], document_ids: list[str] | None = None) -> dict[str, Any]:
        raw = await self.llm.generate('Create exactly 3 concise search queries and one step-back query for the user question. Return JSON: {"queries":[],"step_back":""}. Question: ' + query)
        try:
            parsed = json.loads(re.search(r'\{.*\}', raw, re.S).group(0))
            queries = [query, *[str(q) for q in parsed.get('queries', [])[:4]], str(parsed.get('step_back', query))]
        except Exception:
            queries = [query]
        ranked: dict[str, dict[str, Any]] = {}
        for q in dict.fromkeys(queries):
            results = await self.retrieval.retrieve(user_id, q, top_k=8, document_ids=document_ids)
            for rank, item in enumerate(results, start=1):
                key = str(item.chunk.id)
                slot = ranked.setdefault(key, {'item': item, 'rrf': 0.0})
                slot['rrf'] += 1.0 / (60 + rank)
        ordered = sorted(ranked.values(), key=lambda slot: slot['rrf'], reverse=True)[:8]
        context = []
        for slot in ordered:
            item: RetrievedChunk = slot['item']
            context.append(f"[chunk_id={item.chunk.id}; document_id={item.document.id}; filename={item.document.filename}; page={item.chunk.page_number or 'unknown'}]\n{item.chunk.content[:2200]}")
        history_text = '\n'.join(f"{m['role']}: {m['content'][:1500]}" for m in history[-8:])
        prompt = ('Answer using only the supplied document context. If it does not support an answer, say the information is not available in the documents. '
                  'Return only the answer text.\nCONVERSATION HISTORY:\n' + history_text + '\nQUESTION:\n' + query + '\nDOCUMENT CONTEXT:\n' + '\n\n'.join(context))
        answer = await self.llm.generate(prompt)
        citations = [{'chunk_id': str(slot['item'].chunk.id), 'document_id': slot['item'].document.id,
                      'filename': slot['item'].document.filename, 'page_number': slot['item'].chunk.page_number,
                      'relevance_score': float(slot['rrf'])} for slot in ordered]
        return {'answer': answer, 'citations': citations}
