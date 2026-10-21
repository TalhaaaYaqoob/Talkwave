"""
Knowledge Base Database Client

Handles database operations for knowledge base documents and chunks.
"""

import re
from typing import Dict, List, Optional, Tuple

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from .base_client import BaseDBClient
from .models import KnowledgeBaseChunkModel, KnowledgeBaseDocumentModel

# Postgres rejects NUL (0x00) in text/varchar columns
# (``invalid byte sequence for encoding "UTF8": 0x00``). Strip it plus other
# C0/C1 control chars (keeping tab/newline/carriage-return) before any insert.
_NUL_AND_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _sanitize_for_pg(text: Optional[str]) -> Optional[str]:
    """Strip NUL bytes / control chars so content is safe to persist."""
    if not text:
        return text
    return _NUL_AND_CONTROL_RE.sub("", text)


class KnowledgeBaseClient(BaseDBClient):
    """Database client for knowledge base operations."""

    async def create_document(
        self,
        organization_id: int,
        name: str,
        content: str,
        file_type: str = "txt",
        description: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        created_by: Optional[int] = None,
        workflow_id: Optional[int] = None,
    ) -> KnowledgeBaseDocumentModel:
        """Create a new knowledge base document."""
        content = _sanitize_for_pg(content)
        name = _sanitize_for_pg(name)
        description = _sanitize_for_pg(description)
        async with self.get_session() as session:
            document = KnowledgeBaseDocumentModel(
                organization_id=organization_id,
                workflow_id=workflow_id,
                name=name,
                description=description,
                file_type=file_type,
                file_size_bytes=file_size_bytes,
                content=content,
                processing_status="pending",
                created_by=created_by,
            )
            session.add(document)
            await session.commit()
            await session.refresh(document)
            logger.info(f"Created KB document {document.id}: {name} (workflow_id={workflow_id})")
            return document

    async def get_document(
        self, 
        document_id: int,
        include_chunks: bool = False
    ) -> Optional[KnowledgeBaseDocumentModel]:
        """Get a document by ID."""
        async with self.get_session() as session:
            query = select(KnowledgeBaseDocumentModel).where(
                KnowledgeBaseDocumentModel.id == document_id
            )
            if include_chunks:
                query = query.options(selectinload(KnowledgeBaseDocumentModel.chunks))
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def get_documents_by_organization(
        self,
        organization_id: int,
        active_only: bool = True,
        workflow_id: Optional[int] = None,
    ) -> List[KnowledgeBaseDocumentModel]:
        """Get documents for an organization, optionally scoped to a workflow.

        When *workflow_id* is provided, only documents that explicitly belong
        to that workflow are returned.  Legacy docs with NULL workflow_id are
        excluded to prevent cross-workflow data leaks.
        """
        async with self.get_session() as session:
            query = select(KnowledgeBaseDocumentModel).where(
                KnowledgeBaseDocumentModel.organization_id == organization_id
            )
            if workflow_id is not None:
                query = query.where(
                    KnowledgeBaseDocumentModel.workflow_id == workflow_id
                )
            if active_only:
                query = query.where(KnowledgeBaseDocumentModel.is_active == True)
            query = query.order_by(KnowledgeBaseDocumentModel.created_at.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_document(
        self,
        document_id: int,
        **kwargs
    ) -> Optional[KnowledgeBaseDocumentModel]:
        """Update a document."""
        async with self.get_session() as session:
            result = await session.execute(
                select(KnowledgeBaseDocumentModel).where(
                    KnowledgeBaseDocumentModel.id == document_id
                )
            )
            document = result.scalar_one_or_none()
            if document:
                for key, value in kwargs.items():
                    if hasattr(document, key):
                        setattr(document, key, value)
                await session.commit()
                await session.refresh(document)
            return document

    async def delete_document(self, document_id: int) -> bool:
        """Delete a document and its chunks."""
        async with self.get_session() as session:
            result = await session.execute(
                select(KnowledgeBaseDocumentModel).where(
                    KnowledgeBaseDocumentModel.id == document_id
                )
            )
            document = result.scalar_one_or_none()
            if document:
                await session.delete(document)
                await session.commit()
                logger.info(f"Deleted KB document {document_id}")
                return True
            return False

    async def delete_chunks_by_document(self, document_id: int) -> int:
        """Delete all chunks for a document. Returns number of deleted rows."""
        from sqlalchemy import delete as sa_delete

        async with self.get_session() as session:
            result = await session.execute(
                sa_delete(KnowledgeBaseChunkModel).where(
                    KnowledgeBaseChunkModel.document_id == document_id
                )
            )
            await session.commit()
            count = result.rowcount
            logger.info(f"Deleted {count} chunks for document {document_id}")
            return count

    async def create_chunks(
        self,
        document_id: int,
        chunks: List[dict],
    ) -> List[KnowledgeBaseChunkModel]:
        """Create chunks for a document."""
        async with self.get_session() as session:
            chunk_models = []
            for idx, chunk_data in enumerate(chunks):
                chunk = KnowledgeBaseChunkModel(
                    document_id=document_id,
                    chunk_index=idx,
                    content=_sanitize_for_pg(chunk_data.get("content", "")),
                    token_count=chunk_data.get("token_count"),
                    embedding=chunk_data.get("embedding"),
                )
                session.add(chunk)
                chunk_models.append(chunk)
            
            await session.commit()
            
            # Update document chunk count
            await self.update_document(document_id, chunk_count=len(chunks))
            
            logger.info(f"Created {len(chunks)} chunks for document {document_id}")
            return chunk_models

    async def get_chunks_by_document(
        self,
        document_id: int,
    ) -> List[KnowledgeBaseChunkModel]:
        """Get all chunks for a document."""
        async with self.get_session() as session:
            result = await session.execute(
                select(KnowledgeBaseChunkModel)
                .where(KnowledgeBaseChunkModel.document_id == document_id)
                .order_by(KnowledgeBaseChunkModel.chunk_index)
            )
            return list(result.scalars().all())

    async def search_chunks(
        self,
        organization_id: int,
        query: str,
        limit: int = 5,
        workflow_id: Optional[int] = None,
    ) -> List[KnowledgeBaseChunkModel]:
        """
        Search for relevant chunks across documents in an organization.
        
        When *workflow_id* is given, only documents belonging to that workflow
        (or shared org-level docs with workflow_id=NULL) are searched.
        """
        async with self.get_session() as session:
            doc_query = select(KnowledgeBaseDocumentModel.id).where(
                KnowledgeBaseDocumentModel.organization_id == organization_id,
                KnowledgeBaseDocumentModel.is_active == True,
                KnowledgeBaseDocumentModel.processing_status == "completed",
            )
            if workflow_id is not None:
                doc_query = doc_query.where(
                    KnowledgeBaseDocumentModel.workflow_id == workflow_id
                )
            docs_result = await session.execute(doc_query)
            doc_ids = [row[0] for row in docs_result.fetchall()]
            
            if not doc_ids:
                return []
            
            # Simple keyword search (case-insensitive)
            # In production, use vector similarity search
            search_terms = query.lower().split()
            
            result = await session.execute(
                select(KnowledgeBaseChunkModel)
                .where(
                    KnowledgeBaseChunkModel.document_id.in_(doc_ids)
                )
                .limit(limit * 3)  # Get more to filter
            )
            chunks = list(result.scalars().all())
            
            # Score chunks by keyword matches
            scored_chunks = []
            for chunk in chunks:
                content_lower = chunk.content.lower()
                score = sum(1 for term in search_terms if term in content_lower)
                if score > 0:
                    scored_chunks.append((chunk, score))
            
            # Sort by score and return top results
            scored_chunks.sort(key=lambda x: x[1], reverse=True)
            return [chunk for chunk, _ in scored_chunks[:limit]]

    # ------------------------------------------------------------------
    # Advanced retrieval helpers (for chunk-level semantic search)
    # ------------------------------------------------------------------

    async def get_chunks_with_embeddings_by_organization(
        self,
        organization_id: int,
        workflow_id: Optional[int] = None,
    ) -> List[KnowledgeBaseChunkModel]:
        """Fetch ALL chunks (with embeddings) for completed, active documents.

        Used by the retrieval engine to load pre-computed embeddings into
        memory for fast cosine-similarity search.
        """
        async with self.get_session() as session:
            doc_query = select(KnowledgeBaseDocumentModel.id).where(
                KnowledgeBaseDocumentModel.organization_id == organization_id,
                KnowledgeBaseDocumentModel.is_active == True,
                KnowledgeBaseDocumentModel.processing_status == "completed",
            )
            if workflow_id is not None:
                doc_query = doc_query.where(
                    KnowledgeBaseDocumentModel.workflow_id == workflow_id
                )
            doc_ids_result = await session.execute(doc_query)
            doc_ids = [row[0] for row in doc_ids_result.fetchall()]
            if not doc_ids:
                return []

            result = await session.execute(
                select(KnowledgeBaseChunkModel)
                .where(KnowledgeBaseChunkModel.document_id.in_(doc_ids))
                .order_by(
                    KnowledgeBaseChunkModel.document_id,
                    KnowledgeBaseChunkModel.chunk_index,
                )
            )
            return list(result.scalars().all())

    async def get_neighboring_chunks(
        self,
        document_id: int,
        chunk_indices: List[int],
    ) -> List[KnowledgeBaseChunkModel]:
        """Fetch chunks at *and around* the given indices (±1) for context expansion.

        Returns all chunks whose ``chunk_index`` is in the expanded set,
        ordered by ``chunk_index``.
        """
        if not chunk_indices:
            return []

        expanded = set()
        for idx in chunk_indices:
            expanded.update([max(0, idx - 1), idx, idx + 1])

        async with self.get_session() as session:
            result = await session.execute(
                select(KnowledgeBaseChunkModel)
                .where(
                    KnowledgeBaseChunkModel.document_id == document_id,
                    KnowledgeBaseChunkModel.chunk_index.in_(list(expanded)),
                )
                .order_by(KnowledgeBaseChunkModel.chunk_index)
            )
            return list(result.scalars().all())

    async def update_chunk_embeddings(
        self,
        chunk_ids: List[int],
        embeddings: List[list],
    ) -> int:
        """Batch-update embeddings on existing chunks.

        Returns the number of rows updated.
        """
        if not chunk_ids or len(chunk_ids) != len(embeddings):
            return 0

        updated = 0
        async with self.get_session() as session:
            for cid, emb in zip(chunk_ids, embeddings):
                await session.execute(
                    update(KnowledgeBaseChunkModel)
                    .where(KnowledgeBaseChunkModel.id == cid)
                    .values(embedding=emb)
                )
                updated += 1
            await session.commit()
        logger.info(f"Updated embeddings for {updated} chunks")
        return updated

    async def get_total_token_count(
        self, organization_id: int, workflow_id: Optional[int] = None,
    ) -> int:
        """Sum of token_count across chunks for an org's active, completed docs.

        When *workflow_id* is provided, only counts tokens for documents
        belonging to that workflow (or shared org-level docs).
        """
        async with self.get_session() as session:
            doc_query = select(KnowledgeBaseDocumentModel.id).where(
                KnowledgeBaseDocumentModel.organization_id == organization_id,
                KnowledgeBaseDocumentModel.is_active == True,
                KnowledgeBaseDocumentModel.processing_status == "completed",
            )
            if workflow_id is not None:
                doc_query = doc_query.where(
                    KnowledgeBaseDocumentModel.workflow_id == workflow_id
                )
            doc_ids_result = await session.execute(doc_query)
            doc_ids = [row[0] for row in doc_ids_result.fetchall()]
            if not doc_ids:
                return 0

            result = await session.execute(
                select(
                    func.coalesce(func.sum(KnowledgeBaseChunkModel.token_count), 0)
                ).where(KnowledgeBaseChunkModel.document_id.in_(doc_ids))
            )
            total = result.scalar() or 0

            # If token_count is all NULL, estimate from content length
            if total == 0:
                char_result = await session.execute(
                    select(
                        func.coalesce(func.sum(func.length(KnowledgeBaseChunkModel.content)), 0)
                    ).where(KnowledgeBaseChunkModel.document_id.in_(doc_ids))
                )
                total_chars = char_result.scalar() or 0
                total = total_chars // 4  # rough tokens estimate

            return total

    async def get_chunks_without_embeddings(
        self,
        organization_id: int,
        workflow_id: Optional[int] = None,
    ) -> List[KnowledgeBaseChunkModel]:
        """Fetch chunks that do NOT yet have embeddings (for backfill)."""
        async with self.get_session() as session:
            doc_query = select(KnowledgeBaseDocumentModel.id).where(
                KnowledgeBaseDocumentModel.organization_id == organization_id,
                KnowledgeBaseDocumentModel.is_active == True,
                KnowledgeBaseDocumentModel.processing_status == "completed",
            )
            if workflow_id is not None:
                doc_query = doc_query.where(
                    KnowledgeBaseDocumentModel.workflow_id == workflow_id
                )
            doc_ids_result = await session.execute(doc_query)
            doc_ids = [row[0] for row in doc_ids_result.fetchall()]
            if not doc_ids:
                return []

            result = await session.execute(
                select(KnowledgeBaseChunkModel)
                .where(
                    KnowledgeBaseChunkModel.document_id.in_(doc_ids),
                    KnowledgeBaseChunkModel.embedding.is_(None),
                )
                .order_by(
                    KnowledgeBaseChunkModel.document_id,
                    KnowledgeBaseChunkModel.chunk_index,
                )
            )
            return list(result.scalars().all())

    async def get_document_names_by_ids(
        self,
        document_ids: List[int],
    ) -> Dict[int, str]:
        """Return a mapping of document_id → document_name for the given IDs."""
        if not document_ids:
            return {}
        async with self.get_session() as session:
            result = await session.execute(
                select(
                    KnowledgeBaseDocumentModel.id,
                    KnowledgeBaseDocumentModel.name,
                ).where(KnowledgeBaseDocumentModel.id.in_(document_ids))
            )
            return {row[0]: row[1] for row in result.fetchall()}


# Singleton instance
knowledge_base_client = KnowledgeBaseClient()

