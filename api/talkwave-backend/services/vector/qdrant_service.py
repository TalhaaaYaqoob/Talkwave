"""
Qdrant Cloud Vector Database Service

Manages vector storage and similarity search for knowledge base chunks
using Qdrant Cloud instead of JSONB embeddings in Postgres.
"""

import os
from typing import Dict, List, Optional, Tuple

from loguru import logger
from qdrant_client import AsyncQdrantClient, models

COLLECTION_NAME = "kb_chunks"
EMBEDDING_DIM = 1536  # text-embedding-3-small


def _get_qdrant_client() -> AsyncQdrantClient:
    url = os.getenv("QDRANT_URL", "")
    api_key = os.getenv("QDRANT_API_KEY", "")
    if not url:
        raise ValueError("QDRANT_URL environment variable is not set")
    return AsyncQdrantClient(url=url, api_key=api_key or None)


_client: Optional[AsyncQdrantClient] = None
_collection_ensured = False


async def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = _get_qdrant_client()
    return _client


async def ensure_collection() -> None:
    """Create the kb_chunks collection if it doesn't exist.

    The result is cached for the process lifetime so hot-path searches don't
    pay an extra Qdrant round-trip (~100-300ms) on every call.
    """
    global _collection_ensured
    if _collection_ensured:
        return
    client = await get_client()
    collections = await client.get_collections()
    names = [c.name for c in collections.collections]
    if COLLECTION_NAME not in names:
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIM,
                distance=models.Distance.COSINE,
            ),
        )
        await client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="organization_id",
            field_schema=models.PayloadSchemaType.INTEGER,
        )
        await client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="workflow_id",
            field_schema=models.PayloadSchemaType.INTEGER,
        )
        await client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="document_id",
            field_schema=models.PayloadSchemaType.INTEGER,
        )
        logger.info(f"Created Qdrant collection '{COLLECTION_NAME}'")
    _collection_ensured = True


def _point_id(chunk_db_id: int) -> int:
    """Qdrant point ID derived from the Postgres chunk PK."""
    return chunk_db_id


async def upsert_embeddings(
    chunks: List[Dict],
    embeddings: List[List[float]],
) -> int:
    """Store chunk embeddings in Qdrant.

    Each entry in *chunks* must contain:
        id, document_id, organization_id, chunk_index, content

    Optional: workflow_id, token_count
    """
    if not chunks or not embeddings or len(chunks) != len(embeddings):
        return 0

    await ensure_collection()
    client = await get_client()

    points = []
    for chunk, emb in zip(chunks, embeddings):
        payload = {
            "chunk_db_id": chunk["id"],
            "document_id": chunk["document_id"],
            "organization_id": chunk["organization_id"],
            "chunk_index": chunk.get("chunk_index", 0),
            "content": chunk.get("content", ""),
            "token_count": chunk.get("token_count", 0),
        }
        if chunk.get("workflow_id") is not None:
            payload["workflow_id"] = chunk["workflow_id"]

        points.append(models.PointStruct(
            id=_point_id(chunk["id"]),
            vector=emb,
            payload=payload,
        ))

    batch_size = 100
    upserted = 0
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        await client.upsert(collection_name=COLLECTION_NAME, points=batch)
        upserted += len(batch)

    logger.info(f"Upserted {upserted} vectors into Qdrant")
    return upserted


async def search(
    query_vector: List[float],
    organization_id: int,
    workflow_id: Optional[int] = None,
    top_k: int = 20,
) -> List[Dict]:
    """Semantic search over chunk embeddings.

    Returns list of dicts with keys:
        chunk_db_id, document_id, chunk_index, content, token_count, score
    """
    await ensure_collection()
    client = await get_client()

    must_filters = [
        models.FieldCondition(
            key="organization_id",
            match=models.MatchValue(value=organization_id),
        ),
    ]
    if workflow_id is not None:
        must_filters.append(
            models.FieldCondition(
                key="workflow_id",
                match=models.MatchValue(value=workflow_id),
            )
        )

    results = await client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=models.Filter(must=must_filters),
        limit=top_k,
        with_payload=True,
    )

    hits = []
    for point in results.points:
        payload = point.payload or {}
        hits.append({
            "chunk_db_id": payload.get("chunk_db_id", point.id),
            "document_id": payload.get("document_id"),
            "chunk_index": payload.get("chunk_index", 0),
            "content": payload.get("content", ""),
            "token_count": payload.get("token_count", 0),
            "score": point.score,
        })

    return hits


async def delete_by_document(document_id: int) -> None:
    """Remove all vectors for a document."""
    await ensure_collection()
    client = await get_client()
    await client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    )
                ]
            )
        ),
    )
    logger.info(f"Deleted Qdrant vectors for document {document_id}")


async def delete_by_chunk_ids(chunk_ids: List[int]) -> None:
    """Remove specific vectors by chunk DB IDs."""
    if not chunk_ids:
        return
    await ensure_collection()
    client = await get_client()
    await client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.PointIdsList(
            points=[_point_id(cid) for cid in chunk_ids],
        ),
    )


async def delete_by_organization(organization_id: int) -> None:
    """Remove all vectors for an organization."""
    await ensure_collection()
    client = await get_client()
    await client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="organization_id",
                        match=models.MatchValue(value=organization_id),
                    )
                ]
            )
        ),
    )
    logger.info(f"Deleted all Qdrant vectors for organization {organization_id}")
