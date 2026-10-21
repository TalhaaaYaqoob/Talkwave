"""
Knowledge Base Retrieval Service

Provides intelligent document retrieval using embeddings and hybrid search
for accurate and fast knowledge base queries.

Two retrieval strategies:
  1. Full-load: dump all KB content into the LLM context (small KBs < 30K tokens)
  2. Chunk-level search: hybrid semantic + BM25 search over pre-computed chunk
     embeddings with context expansion (large KBs >= 30K tokens)
"""

import asyncio
import hashlib
import os
import time
from collections import OrderedDict
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass

import numpy as np
from loguru import logger
from openai import AsyncOpenAI

from api.db.knowledge_base_client import knowledge_base_client
from api.db.models import KnowledgeBaseChunkModel, KnowledgeBaseDocumentModel


class _LRUCache:
    """Simple thread-safe LRU cache with a max entry limit."""

    def __init__(self, maxsize: int = 500):
        self._data: OrderedDict = OrderedDict()
        self._maxsize = maxsize
        self._lock = asyncio.Lock()

    async def get(self, key):
        async with self._lock:
            val = self._data.get(key)
            if val is not None:
                self._data.move_to_end(key)
            return val

    def get_sync(self, key):
        val = self._data.get(key)
        if val is not None:
            self._data.move_to_end(key)
        return val

    async def put(self, key, value):
        async with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def put_sync(self, key, value):
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    async def pop(self, key, default=None):
        async with self._lock:
            return self._data.pop(key, default)

    def __len__(self):
        return len(self._data)

    def items(self):
        return list(self._data.items())


_embedding_cache = _LRUCache(maxsize=2000)

_retrieval_cache = _LRUCache(maxsize=500)
_RETRIEVAL_CACHE_TTL = 120

_chunk_embedding_cache = _LRUCache(maxsize=200)
_CHUNK_EMBEDDING_CACHE_TTL = 300

_token_count_cache = _LRUCache(maxsize=200)
_TOKEN_COUNT_CACHE_TTL = 300

KB_SIZE_THRESHOLD_TOKENS = 100_000


def _log_kb(message: str, level: str = "info"):
    """Helper to log KB messages with a clear prefix."""
    prefix = "📚 [KNOWLEDGE BASE]"
    if level == "debug":
        logger.debug(f"{prefix} {message}")
    elif level == "warning":
        logger.warning(f"{prefix} {message}")
    elif level == "error":
        logger.error(f"{prefix} {message}")
    else:
        logger.info(f"{prefix} {message}")


@dataclass
class RetrievedDocument:
    """Represents a retrieved document with its relevance score."""
    document_id: int
    document_name: str
    content: str
    score: float
    chunk_count: int
    is_full_document: bool


@dataclass
class RetrievalResult:
    """Result of a knowledge base retrieval operation."""
    documents: List[RetrievedDocument]
    total_tokens_estimate: int
    query_used: str


class KnowledgeBaseRetriever:
    """
    Intelligent knowledge base retrieval using hybrid search:
    1. Semantic search with OpenAI embeddings
    2. Keyword-based BM25-style scoring
    3. Document-level aggregation and ranking
    4. Full document retrieval when beneficial
    """

    def __init__(
        self,
        embedding_model: str = "text-embedding-3-small",
        max_context_tokens: int = 8000,  # Leave room for conversation
    ):
        self.embedding_model = embedding_model
        self.max_context_tokens = max_context_tokens
        self._client: Optional[AsyncOpenAI] = None
        self._api_key: Optional[str] = None

    def set_api_key(self, api_key: str):
        """Set the API key for OpenAI embeddings."""
        if api_key != self._api_key:
            self._api_key = api_key
            self._client = None  # Reset client to use new key
            _log_kb(f"API key set (prefix: {api_key[:10]}...)", "debug")

    def _get_api_key(self) -> Optional[str]:
        """Get API key from instance or environment."""
        if self._api_key:
            return self._api_key
        return os.environ.get("OPENAI_API_KEY")

    @property
    def client(self) -> AsyncOpenAI:
        """Lazy-load OpenAI client."""
        if self._client is None:
            api_key = self._get_api_key()
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            self._client = AsyncOpenAI(api_key=api_key)
        return self._client

    async def get_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text with caching."""
        results = await self.get_embeddings_batch([text])
        return results[0]

    async def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for multiple texts in a single API call with caching.

        This is dramatically faster than calling get_embedding() in a loop:
        - 1 API call for N texts instead of N API calls
        - Cached texts are returned instantly, only uncached texts hit the API
        """
        results: List[Optional[List[float]]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        for i, text in enumerate(texts):
            cache_key = hashlib.md5(text.encode()).hexdigest()
            cached = _embedding_cache.get_sync(cache_key)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_indices:
            _log_kb(
                f"Embedding batch: {len(texts)} total, {len(texts) - len(uncached_indices)} cached, "
                f"{len(uncached_indices)} to fetch",
                "debug",
            )
            try:
                start_time = time.time()
                response = await self.client.embeddings.create(
                    model=self.embedding_model,
                    input=uncached_texts,
                )
                elapsed = time.time() - start_time
                _log_kb(f"Got {len(uncached_texts)} embeddings in {elapsed:.2f}s (single API call)", "debug")

                for j, emb_data in enumerate(response.data):
                    idx = uncached_indices[j]
                    embedding = emb_data.embedding
                    results[idx] = embedding
                    cache_key = hashlib.md5(uncached_texts[j].encode()).hexdigest()
                    _embedding_cache.put_sync(cache_key, embedding)

            except Exception as e:
                _log_kb(f"Failed to get batch embeddings: {e}", "error")
                raise
        else:
            _log_kb(f"Embedding batch: all {len(texts)} served from cache", "debug")

        return results  # type: ignore[return-value]

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors (vectorized)."""
        if not a or not b or len(a) != len(b):
            return 0.0

        va = np.asarray(a, dtype=np.float32)
        vb = np.asarray(b, dtype=np.float32)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        if denom == 0.0:
            return 0.0
        return float(np.dot(va, vb) / denom)

    def bm25_score(
        self, 
        query_terms: List[str], 
        document: str,
        k1: float = 1.5,
        b: float = 0.75,
        avg_doc_length: float = 500,
    ) -> float:
        """
        Calculate BM25-style score for keyword matching.
        This provides a fast fallback when embeddings aren't available.
        """
        doc_lower = document.lower()
        doc_length = len(doc_lower.split())
        
        score = 0.0
        for term in query_terms:
            term_lower = term.lower()
            # Count term frequency
            tf = doc_lower.count(term_lower)
            if tf > 0:
                # BM25 term frequency saturation
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * (doc_length / avg_doc_length))
                score += numerator / denominator
        
        return score

    async def retrieve(
        self,
        organization_id: int,
        query: str,
        top_k_documents: int = 5,
        use_embeddings: bool = True,
        workflow_id: Optional[int] = None,
    ) -> RetrievalResult:
        """
        Retrieve the most relevant documents for a query.
        
        Strategy:
        1. Get all documents for the organization
        2. Score each document using hybrid search (embeddings + keywords)
        3. Rank and select top K documents
        4. Return full documents when small enough, otherwise best chunks
        
        Args:
            organization_id: The organization to search within
            query: The user's query
            top_k_documents: Maximum number of documents to return
            use_embeddings: Whether to use embedding-based search
            
        Returns:
            RetrievalResult with ranked documents and metadata
        """
        retrieval_start = time.time()
        
        _log_kb("=" * 60)
        _log_kb(f"🔍 RETRIEVAL STARTED")
        _log_kb(f"   Query: '{query[:100]}{'...' if len(query) > 100 else ''}'")
        _log_kb(f"   Organization ID: {organization_id}")
        _log_kb(f"   Top K: {top_k_documents}")
        _log_kb(f"   Use Embeddings: {use_embeddings}")
        _log_kb("=" * 60)
        
        # Get all documents for the organization (scoped to the workflow when
        # provided, so retrieval never leaks other workflows' documents and
        # scores fewer candidates → faster + more accurate).
        _log_kb("Fetching documents from database...")
        documents = await knowledge_base_client.get_documents_by_organization(
            organization_id=organization_id,
            active_only=True,
            workflow_id=workflow_id,
        )
        
        if not documents:
            _log_kb("❌ No documents found for organization!", "warning")
            return RetrievalResult(documents=[], total_tokens_estimate=0, query_used=query)
        
        _log_kb(f"Found {len(documents)} total documents")
        
        # Filter to only completed documents
        documents = [d for d in documents if d.processing_status == "completed"]
        
        if not documents:
            _log_kb("❌ No completed documents found!", "warning")
            return RetrievalResult(documents=[], total_tokens_estimate=0, query_used=query)
        
        _log_kb(f"✓ {len(documents)} completed documents ready for search")
        for doc in documents:
            _log_kb(f"   📄 '{doc.name}' (ID: {doc.id}, {len(doc.content)} chars, {doc.chunk_count} chunks)", "debug")
        
        # Score each document
        scored_documents: List[Tuple[KnowledgeBaseDocumentModel, float]] = []
        
        # Prepare query terms for keyword search (always needed)
        query_terms = [term for term in query.lower().split() if len(term) > 2]
        
        # LATENCY FIX: Fetch query + ALL document embeddings in a single batch API call.
        # Previously each document was embedded sequentially (~300ms each = 1.5s for 5 docs).
        # Now it's 1 API call for everything (~300ms total).
        doc_embeddings: List[Optional[List[float]]] = [None] * len(documents)
        query_embedding: Optional[List[float]] = None
        
        if use_embeddings:
            try:
                # Build batch: query text + all document texts
                batch_texts = [query]
                for doc in documents:
                    batch_texts.append(f"{doc.name}. {doc.description or ''} {doc.content[:1000]}")
                
                _log_kb(f"Fetching {len(batch_texts)} embeddings in single batch (1 query + {len(documents)} docs)...")
                all_embeddings = await self.get_embeddings_batch(batch_texts)
                
                query_embedding = all_embeddings[0]
                for i in range(len(documents)):
                    doc_embeddings[i] = all_embeddings[i + 1]
                
                _log_kb(f"✓ All embeddings ready")
            except Exception as e:
                _log_kb(f"⚠️ Batch embedding failed, falling back to keyword search: {e}", "warning")
                use_embeddings = False
        
        _log_kb("Scoring documents...")
        for i, doc in enumerate(documents):
            score = 0.0
            semantic_score = 0.0
            keyword_score = 0.0
            name_boost = 0.0
            
            # Semantic similarity score
            if use_embeddings and query_embedding and doc_embeddings[i]:
                semantic_score = self.cosine_similarity(query_embedding, doc_embeddings[i])
                score += semantic_score * 0.7
            
            # Keyword/BM25 score
            raw_keyword_score = self.bm25_score(query_terms, doc.content)
            keyword_score = min(raw_keyword_score / 10, 1.0)
            score += keyword_score * 0.3
            
            # Boost for title/name matches
            name_lower = doc.name.lower()
            for term in query_terms:
                if term in name_lower:
                    name_boost += 0.2
            score += name_boost
            
            _log_kb(
                f"   📊 '{doc.name}': "
                f"semantic={semantic_score:.3f}, keyword={keyword_score:.3f}, name_boost={name_boost:.1f} "
                f"→ TOTAL={score:.3f}",
                "debug"
            )
            
            scored_documents.append((doc, score))
        
        # Sort by score descending
        scored_documents.sort(key=lambda x: x[1], reverse=True)
        
        # Select top K documents
        top_documents = scored_documents[:top_k_documents]
        
        _log_kb(f"📈 Top {len(top_documents)} ranked documents:")
        for i, (doc, score) in enumerate(top_documents, 1):
            _log_kb(f"   #{i}: '{doc.name}' (score: {score:.3f})")
        
        # Build result with full documents when possible
        retrieved_documents: List[RetrievedDocument] = []
        total_tokens = 0
        
        _log_kb("Building context from top documents...")
        for doc, score in top_documents:
            # Estimate tokens (roughly 4 chars per token)
            doc_tokens = len(doc.content) // 4
            
            # Check if we can include the full document
            if total_tokens + doc_tokens <= self.max_context_tokens:
                retrieved_documents.append(RetrievedDocument(
                    document_id=doc.id,
                    document_name=doc.name,
                    content=doc.content,
                    score=score,
                    chunk_count=doc.chunk_count,
                    is_full_document=True,
                ))
                total_tokens += doc_tokens
                _log_kb(f"   ✓ Added FULL document '{doc.name}' (~{doc_tokens} tokens)")
            else:
                # Document too large, truncate intelligently
                available_tokens = self.max_context_tokens - total_tokens
                if available_tokens > 200:  # Only include if meaningful amount left
                    # Truncate to available space
                    available_chars = available_tokens * 4
                    truncated_content = doc.content[:available_chars]
                    # Try to end at a sentence
                    last_period = truncated_content.rfind('.')
                    if last_period > available_chars * 0.7:
                        truncated_content = truncated_content[:last_period + 1]
                    
                    retrieved_documents.append(RetrievedDocument(
                        document_id=doc.id,
                        document_name=doc.name,
                        content=truncated_content + "\n[Document truncated...]",
                        score=score,
                        chunk_count=doc.chunk_count,
                        is_full_document=False,
                    ))
                    total_tokens += len(truncated_content) // 4
                    _log_kb(f"   ⚠️ Added TRUNCATED document '{doc.name}' (~{len(truncated_content)//4} tokens)")
                else:
                    _log_kb(f"   ✗ Skipped '{doc.name}' - no room left in context")
                break  # No more room
        
        elapsed = time.time() - retrieval_start
        
        _log_kb("=" * 60)
        _log_kb(f"✅ RETRIEVAL COMPLETE")
        _log_kb(f"   Documents Retrieved: {len(retrieved_documents)}")
        _log_kb(f"   Total Tokens: ~{total_tokens}")
        _log_kb(f"   Top Score: {top_documents[0][1] if top_documents else 0:.3f}")
        _log_kb(f"   Time Elapsed: {elapsed:.2f}s")
        _log_kb("=" * 60)
        
        return RetrievalResult(
            documents=retrieved_documents,
            total_tokens_estimate=total_tokens,
            query_used=query,
        )

    def format_context_for_llm(
        self,
        result: RetrievalResult,
        include_source_names: bool = True,
    ) -> str:
        """
        Format retrieved documents into a context string for the LLM.
        
        Args:
            result: The retrieval result
            include_source_names: Whether to include document names as headers
            
        Returns:
            Formatted context string to inject into the prompt
        """
        if not result.documents:
            _log_kb("No documents to format for LLM context", "debug")
            return ""
        
        _log_kb(f"Formatting {len(result.documents)} documents for LLM context...")
        
        context_parts = []
        context_parts.append("=== KNOWLEDGE BASE INFORMATION ===")
        context_parts.append("Use the following information to answer questions accurately:\n")
        
        for i, doc in enumerate(result.documents, 1):
            if include_source_names:
                context_parts.append(f"--- Document {i}: {doc.document_name} ---")
            context_parts.append(doc.content)
            context_parts.append("")  # Empty line between documents
            _log_kb(f"   Added doc {i}: '{doc.document_name}' ({len(doc.content)} chars)", "debug")
        
        context_parts.append("=== END KNOWLEDGE BASE ===\n")
        
        formatted = "\n".join(context_parts)
        _log_kb(f"✓ Formatted context ready ({len(formatted)} chars)")
        
        return formatted

    # ------------------------------------------------------------------
    # Chunk-level retrieval via Qdrant
    # ------------------------------------------------------------------

    async def retrieve_chunks(
        self,
        organization_id: int,
        query: str,
        top_k: int = 20,
        max_context_tokens: int = 12000,
        workflow_id: Optional[int] = None,
    ) -> str:
        """Chunk-level hybrid retrieval using Qdrant vector search.

        Strategy:
        1. Embed the query via OpenAI.
        2. Search Qdrant for top-K similar chunks (filtered by org/workflow).
        3. Re-rank with BM25 keyword boost.
        4. Expand context with neighboring chunks (±1) from Postgres.
        5. Merge overlapping chunks into passages.
        6. Fit within token budget and format for LLM.

        Returns a formatted context string ready for the system prompt.
        """
        from api.services.vector import qdrant_service

        retrieval_start = time.time()
        _log_kb("=" * 60)
        _log_kb("🔍 CHUNK-LEVEL RETRIEVAL (Qdrant) STARTED")
        _log_kb(f"   Query: '{query[:100]}{'...' if len(query) > 100 else ''}'")
        _log_kb(f"   Organization ID: {organization_id}")
        _log_kb(f"   Top-K: {top_k}, Max Tokens: {max_context_tokens}")
        _log_kb("=" * 60)

        # 1. Embed the query
        try:
            query_embedding = await self.get_embedding(query)
        except Exception as e:
            _log_kb(f"⚠️ Query embedding failed: {e}", "warning")
            return ""

        # 2. Qdrant vector search
        try:
            qdrant_hits = await qdrant_service.search(
                query_vector=query_embedding,
                organization_id=organization_id,
                workflow_id=workflow_id,
                top_k=top_k * 2,  # fetch extra for BM25 re-ranking
            )
        except Exception as e:
            _log_kb(f"⚠️ Qdrant search failed: {e}", "warning")
            return ""

        if not qdrant_hits:
            _log_kb("❌ No chunks found in Qdrant", "warning")
            return ""

        _log_kb(f"Qdrant returned {len(qdrant_hits)} hits")

        # 3. Re-rank with BM25 hybrid scoring
        query_terms = [t for t in query.lower().split() if len(t) > 2]
        scored = []
        for hit in qdrant_hits:
            sem = hit["score"]
            kw = self.bm25_score(query_terms, hit["content"])
            kw_norm = min(kw / 10.0, 1.0)
            hybrid = sem * 0.7 + kw_norm * 0.3
            scored.append((hit, hybrid))

        scored.sort(key=lambda x: x[1], reverse=True)
        top_hits = scored[:top_k]

        _log_kb(f"Top {len(top_hits)} chunks after hybrid re-rank (best={top_hits[0][1]:.3f})")

        # 4. Expand context with neighboring chunks (±1)
        doc_chunk_map: Dict[int, set] = {}
        idx_to_score: Dict[Tuple[int, int], float] = {}
        chunk_lookup: Dict[Tuple[int, int], dict] = {}

        for hit, score in top_hits:
            doc_id = hit["document_id"]
            cidx = hit["chunk_index"]
            doc_chunk_map.setdefault(doc_id, set()).add(cidx)
            idx_to_score[(doc_id, cidx)] = score
            chunk_lookup[(doc_id, cidx)] = hit

        expanded_map: Dict[int, set] = {}
        for doc_id, indices in doc_chunk_map.items():
            expanded = set()
            for idx in indices:
                expanded.update([max(0, idx - 1), idx, idx + 1])
            expanded_map[doc_id] = expanded

        # Fetch neighboring chunks from Postgres — one concurrent query per
        # document instead of sequential awaits (saves ~50-100ms per extra doc
        # while the caller is waiting mid-conversation).
        neighbor_jobs = [
            (doc_id, [ci for ci in expanded_indices if (doc_id, ci) not in chunk_lookup])
            for doc_id, expanded_indices in expanded_map.items()
        ]
        neighbor_jobs = [(d, m) for d, m in neighbor_jobs if m]
        if neighbor_jobs:
            neighbor_results = await asyncio.gather(
                *(
                    knowledge_base_client.get_neighboring_chunks(doc_id, missing)
                    for doc_id, missing in neighbor_jobs
                ),
                return_exceptions=True,
            )
            for (doc_id, _), neighbors in zip(neighbor_jobs, neighbor_results):
                if isinstance(neighbors, Exception):
                    _log_kb(f"⚠️ Neighbor fetch failed for doc {doc_id}: {neighbors}", "warning")
                    continue
                for n in neighbors:
                    key = (doc_id, n.chunk_index)
                    if key not in chunk_lookup:
                        chunk_lookup[key] = {
                            "document_id": doc_id,
                            "chunk_index": n.chunk_index,
                            "content": n.content,
                            "token_count": n.token_count or (len(n.content) // 4),
                        }

        # 5. Merge into contiguous passages
        doc_ids = list(expanded_map.keys())
        doc_names = await knowledge_base_client.get_document_names_by_ids(doc_ids)

        passages: List[Tuple[str, str, float]] = []

        for doc_id, expanded_indices in expanded_map.items():
            doc_name = doc_names.get(doc_id, f"Document {doc_id}")
            sorted_indices = sorted(expanded_indices)

            ranges: List[List[int]] = []
            current_range: List[int] = []
            for idx in sorted_indices:
                if current_range and idx > current_range[-1] + 1:
                    ranges.append(current_range)
                    current_range = [idx]
                else:
                    current_range.append(idx)
            if current_range:
                ranges.append(current_range)

            for rng in ranges:
                texts = []
                best_score = 0.0
                for cidx in rng:
                    key = (doc_id, cidx)
                    cd = chunk_lookup.get(key)
                    if cd:
                        texts.append(cd["content"])
                        s = idx_to_score.get(key, 0.0)
                        best_score = max(best_score, s)

                if texts:
                    merged = texts[0]
                    for t in texts[1:]:
                        overlap_len = min(300, len(merged), len(t))
                        best_overlap = 0
                        for ol in range(20, overlap_len):
                            if merged[-ol:] == t[:ol]:
                                best_overlap = ol
                        if best_overlap > 0:
                            merged += t[best_overlap:]
                        else:
                            merged += "\n\n" + t

                    passages.append((doc_name, merged, best_score))

        passages.sort(key=lambda x: x[2], reverse=True)

        # 6. Fit within token budget
        context_parts = [
            "=== KNOWLEDGE BASE INFORMATION ===",
            "Use the following information to answer questions accurately. "
            "These are the most relevant passages from the knowledge base.\n",
        ]
        total_tokens = 0
        included = 0

        for doc_name, passage, score in passages:
            passage_tokens = len(passage.split()) * 4 // 3
            if total_tokens + passage_tokens > max_context_tokens:
                remaining = max_context_tokens - total_tokens
                if remaining > 200:
                    available_chars = remaining * 3
                    truncated = passage[:available_chars]
                    last_period = truncated.rfind('. ')
                    if last_period > available_chars * 0.5:
                        truncated = truncated[:last_period + 1]
                    context_parts.append(f"--- From: {doc_name} (relevance: {score:.2f}) ---")
                    context_parts.append(truncated + "\n[Passage truncated...]")
                    context_parts.append("")
                    included += 1
                break

            context_parts.append(f"--- From: {doc_name} (relevance: {score:.2f}) ---")
            context_parts.append(passage)
            context_parts.append("")
            total_tokens += passage_tokens
            included += 1

        context_parts.append("=== END KNOWLEDGE BASE ===\n")
        context = "\n".join(context_parts)

        elapsed = time.time() - retrieval_start
        _log_kb("=" * 60)
        _log_kb(f"✅ CHUNK RETRIEVAL COMPLETE (Qdrant)")
        _log_kb(f"   Passages included: {included}")
        _log_kb(f"   Total tokens: ~{total_tokens}")
        _log_kb(f"   Context length: {len(context)} chars")
        _log_kb(f"   Time: {elapsed:.2f}s")
        _log_kb("=" * 60)

        return context


# Singleton instance
knowledge_base_retriever = KnowledgeBaseRetriever()


_full_kb_cache = _LRUCache(maxsize=200)
_FULL_KB_CACHE_TTL = 300


async def load_all_knowledge_for_agent(
    organization_id: int,
    llm_description: Optional[str] = None,
    max_tokens: int = 100_000,
    workflow_id: Optional[int] = None,
) -> str:
    """Load ALL knowledge base documents for a workflow — no search, no ranking.

    When *workflow_id* is provided, only documents belonging to that workflow
    (or shared org-level docs with workflow_id=NULL) are loaded.

    Falls back to an empty string if there are no documents.
    """
    cache_key = (organization_id, workflow_id)
    cached = await _full_kb_cache.get(cache_key)
    if cached is not None:
        cached_context, cached_ts = cached
        if time.time() - cached_ts < _FULL_KB_CACHE_TTL:
            _log_kb(f"✅ Full KB cache HIT (org={organization_id}, wf={workflow_id}, {len(cached_context)} chars)")
            return cached_context
        else:
            await _full_kb_cache.pop(cache_key)

    _log_kb(f"Loading ALL KB documents for org {organization_id} workflow {workflow_id} (no search)...")
    try:
        documents = await knowledge_base_client.get_documents_by_organization(
            organization_id=organization_id, active_only=True, workflow_id=workflow_id,
        )
        documents = [d for d in documents if d.processing_status == "completed"]
        if not documents:
            _log_kb("No completed KB documents found", "warning")
            await _full_kb_cache.put(cache_key, ("", time.time()))
            return ""

        parts = ["=== KNOWLEDGE BASE INFORMATION ===",
                 "Use the following information to answer questions accurately. "
                 "This is the COMPLETE knowledge base — do NOT say you don't have information if it's here.\n"]

        if llm_description:
            parts.append(f"Knowledge Base Purpose: {llm_description}\n")

        total_tokens = 0
        for i, doc in enumerate(documents, 1):
            doc_tokens = len(doc.content) // 4
            if total_tokens + doc_tokens > max_tokens:
                _log_kb(f"Reached {max_tokens} token limit after {i-1} documents", "warning")
                break
            parts.append(f"--- Document {i}: {doc.name} ---")
            parts.append(doc.content)
            parts.append("")
            total_tokens += doc_tokens
            _log_kb(f"   Added '{doc.name}' (~{doc_tokens} tokens)", "debug")

        parts.append("=== END KNOWLEDGE BASE ===\n")
        context = "\n".join(parts)

        _log_kb(f"✅ Full KB loaded: {len(documents)} docs, ~{total_tokens} tokens, {len(context)} chars")
        await _full_kb_cache.put(cache_key, (context, time.time()))
        return context

    except Exception as e:
        _log_kb(f"Failed to load full KB: {e}", "error")
        return ""


async def embed_and_store_chunks(
    chunk_ids: List[int],
    chunk_contents: List[str],
    api_key: Optional[str] = None,
    organization_id: Optional[int] = None,
    document_id: Optional[int] = None,
    workflow_id: Optional[int] = None,
) -> int:
    """Pre-compute embeddings and store in both Postgres (JSONB) and Qdrant.

    Called during document ingestion so retrieval queries can skip the
    embedding-generation step entirely.

    Args:
        chunk_ids: Database IDs of the chunks.
        chunk_contents: Text content of each chunk (same order as chunk_ids).
        api_key: Optional OpenAI API key (falls back to env var).
        organization_id: Org ID for Qdrant payload filtering.
        document_id: Document ID for Qdrant payload.
        workflow_id: Workflow ID for Qdrant payload filtering.

    Returns:
        Number of chunks successfully embedded.
    """
    if not chunk_ids or not chunk_contents:
        return 0

    _log_kb(f"Pre-computing embeddings for {len(chunk_ids)} chunks...")

    if api_key:
        knowledge_base_retriever.set_api_key(api_key)

    try:
        embeddings = await knowledge_base_retriever.get_embeddings_batch(chunk_contents)

        from api.db.knowledge_base_client import knowledge_base_client as kb_client
        updated = await kb_client.update_chunk_embeddings(chunk_ids, embeddings)

        # Also push to Qdrant if org info is available
        if organization_id is not None:
            try:
                from api.services.vector import qdrant_service
                qdrant_chunks = []
                for i, cid in enumerate(chunk_ids):
                    qdrant_chunks.append({
                        "id": cid,
                        "document_id": document_id,
                        "organization_id": organization_id,
                        "workflow_id": workflow_id,
                        "chunk_index": i,
                        "content": chunk_contents[i],
                        "token_count": len(chunk_contents[i]) // 4,
                    })
                await qdrant_service.upsert_embeddings(qdrant_chunks, embeddings)
                _log_kb(f"✅ Stored {len(chunk_ids)} embeddings in Qdrant")
            except Exception as qe:
                _log_kb(f"⚠️ Qdrant upsert failed (non-fatal): {qe}", "warning")

        _log_kb(f"✅ Pre-computed & stored embeddings for {updated} chunks")
        return updated
    except Exception as e:
        _log_kb(f"⚠️ Failed to pre-compute embeddings (non-fatal): {e}", "warning")
        return 0


async def get_kb_total_tokens(
    organization_id: int, workflow_id: Optional[int] = None,
) -> int:
    """Return the total token count for an org/workflow's KB (cached)."""
    cache_key = (organization_id, workflow_id)
    cached = await _token_count_cache.get(cache_key)
    if cached is not None:
        count, ts = cached
        if time.time() - ts < _TOKEN_COUNT_CACHE_TTL:
            return count
        await _token_count_cache.pop(cache_key)

    count = await knowledge_base_client.get_total_token_count(
        organization_id, workflow_id=workflow_id,
    )
    await _token_count_cache.put(cache_key, (count, time.time()))
    _log_kb(f"KB total tokens for org {organization_id} workflow {workflow_id}: ~{count}")
    return count


async def retrieve_chunks_for_agent(
    organization_id: int,
    user_query: str,
    llm_description: Optional[str] = None,
    top_k: int = 20,
    max_context_tokens: int = 12000,
    api_key: Optional[str] = None,
    workflow_id: Optional[int] = None,
) -> str:
    """High-level wrapper for chunk-level retrieval.

    Designed for large KBs (>= 30K tokens).  Uses pre-computed chunk
    embeddings for instant cosine similarity, hybrid BM25 scoring, and
    context expansion (neighboring chunks).

    When *workflow_id* is provided, only chunks from documents that
    belong to that workflow (or shared org-level docs) are searched.
    """
    _log_kb("🚀 CHUNK-LEVEL RETRIEVAL FOR AGENT")
    _log_kb(f"   Query: '{user_query[:80]}'")

    if api_key:
        knowledge_base_retriever.set_api_key(api_key)

    cache_key = hashlib.md5(
        f"chunks:{organization_id}:{workflow_id}:{user_query}:{top_k}".encode()
    ).hexdigest()
    cached = await _retrieval_cache.get(cache_key)
    if cached is not None:
        cached_context, cached_ts = cached
        if time.time() - cached_ts < _RETRIEVAL_CACHE_TTL:
            _log_kb("✅ Chunk retrieval cache HIT")
            return cached_context
        await _retrieval_cache.pop(cache_key)

    try:
        context = await knowledge_base_retriever.retrieve_chunks(
            organization_id=organization_id,
            query=user_query,
            top_k=top_k,
            max_context_tokens=max_context_tokens,
            workflow_id=workflow_id,
        )

        if llm_description and context:
            context = f"Knowledge Base Purpose: {llm_description}\n\n{context}"

        await _retrieval_cache.put(cache_key, (context, time.time()))
        return context

    except Exception as e:
        _log_kb(f"❌ Chunk retrieval failed: {e}", "error")
        import traceback
        _log_kb(f"Traceback: {traceback.format_exc()}", "error")
        return ""


async def retrieve_knowledge_for_agent(
    organization_id: int,
    user_query: str,
    llm_description: Optional[str] = None,
    query_override: Optional[str] = None,
    document_limit: int = 5,
    api_key: Optional[str] = None,
    workflow_id: Optional[int] = None,
) -> str:
    """
    High-level function to retrieve knowledge base context for an agent.
    
    Args:
        organization_id: The organization ID
        user_query: The user's question/query
        llm_description: Optional description of what the KB contains (for better retrieval)
        query_override: Optional override for the search query
        document_limit: Maximum documents to retrieve
        api_key: Optional OpenAI API key for embeddings (falls back to env var if not provided)
        
    Returns:
        Formatted context string to add to the system prompt
    """
    _log_kb("*" * 60)
    _log_kb("🚀 AGENT KNOWLEDGE BASE RETRIEVAL CALLED")
    _log_kb(f"   Organization: {organization_id}")
    _log_kb(f"   User Query: '{user_query[:80]}{'...' if len(user_query) > 80 else ''}'")
    _log_kb(f"   Query Override: {query_override or 'None'}")
    _log_kb(f"   LLM Description: {llm_description or 'None'}")
    _log_kb(f"   Document Limit: {document_limit}")
    _log_kb(f"   API Key Provided: {'Yes' if api_key else 'No (using env var)'}")
    _log_kb("*" * 60)
    
    # Set API key if provided
    if api_key:
        knowledge_base_retriever.set_api_key(api_key)
    
    # Use query override if provided, otherwise use user query
    search_query = query_override if query_override else user_query

    cache_key = hashlib.md5(
        f"{organization_id}:{workflow_id}:{search_query}:{document_limit}".encode()
    ).hexdigest()
    cached = await _retrieval_cache.get(cache_key)
    if cached is not None:
        cached_context, cached_ts = cached
        if time.time() - cached_ts < _RETRIEVAL_CACHE_TTL:
            _log_kb(f"✅ Retrieval cache HIT (org={organization_id}, query='{search_query[:40]}...')")
            return cached_context
        else:
            await _retrieval_cache.pop(cache_key)
    
    try:
        result = await knowledge_base_retriever.retrieve(
            organization_id=organization_id,
            query=search_query,
            top_k_documents=document_limit,
            use_embeddings=True,
            workflow_id=workflow_id,
        )
        
        if not result.documents:
            _log_kb("❌ No relevant documents found in knowledge base", "warning")
            await _retrieval_cache.put(cache_key, ("", time.time()))
            return ""
        
        context = knowledge_base_retriever.format_context_for_llm(result)
        
        # Add LLM description if provided
        if llm_description and context:
            context = f"Knowledge Base Purpose: {llm_description}\n\n{context}"
            _log_kb(f"Added LLM description header to context")
        
        _log_kb("*" * 60)
        _log_kb(f"✅ KNOWLEDGE BASE CONTEXT READY")
        _log_kb(f"   Total Context Length: {len(context)} chars")
        _log_kb(f"   Documents Included: {len(result.documents)}")
        _log_kb(f"   Preview: {context[:200]}...")
        _log_kb("*" * 60)

        await _retrieval_cache.put(cache_key, (context, time.time()))
        
        return context
        
    except Exception as e:
        _log_kb(f"❌ FAILED to retrieve knowledge base context: {e}", "error")
        import traceback
        _log_kb(f"Traceback: {traceback.format_exc()}", "error")
        return ""

