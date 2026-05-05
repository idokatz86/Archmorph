"""
RAG (Retrieval-Augmented Generation) API routes.

Provides endpoints for managing document collections, ingesting documents,
and performing semantic search for HLD/IaC context augmentation.

Issue #395 — Track 1 Product Value feature.
"""

import asyncio
import logging
import os
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from pydantic import Field
from strict_models import StrictBaseModel

from error_envelope import ArchmorphException
from routers.shared import limiter, verify_api_key
from usage_metrics import record_event

logger = logging.getLogger(__name__)

router = APIRouter()

# Max upload size: 20 MB
MAX_UPLOAD_SIZE = int(os.getenv("RAG_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))


# ─────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────
class CreateCollectionRequest(StrictBaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class CollectionResponse(StrictBaseModel):
    collection_id: str
    name: str
    description: str
    created_at: str


class DocumentResponse(StrictBaseModel):
    document_id: str
    filename: str
    file_size: int
    chunk_count: int
    content_hash: str
    ingested_at: str
    mime_type: str = ""


class IngestResponse(StrictBaseModel):
    document_id: str
    filename: str
    status: str
    chunk_count: int
    file_size: int = 0
    content_hash: str = ""
    message: str = ""


class SearchRequest(StrictBaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    collection_ids: Optional[List[str]] = Field(default=None)
    top_k: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata_filter: Optional[Dict[str, str]] = Field(default=None)


class SearchResultItem(StrictBaseModel):
    text: str
    score: float
    vector_score: float
    bm25_score: float
    source_document: str
    document_id: str
    page: int
    chunk_index: int
    collection_id: str
    collection_name: str


class SearchResponse(StrictBaseModel):
    results: List[SearchResultItem]
    query: str
    total_results: int


class CollectionStats(StrictBaseModel):
    collection_id: str
    name: str
    description: str
    created_at: str
    document_count: int
    chunk_count: int
    total_tokens: int


# ─────────────────────────────────────────────────────────────
# Collection Endpoints
# ─────────────────────────────────────────────────────────────
@router.post("/api/rag/collections", response_model=CollectionResponse)
@limiter.limit("20/minute")
async def create_collection(
    request: Request,
    body: CreateCollectionRequest,
    _auth=Depends(verify_api_key),
):
    """Create a new document collection for RAG."""
    from rag_pipeline import VectorStore

    store = VectorStore.instance()
    coll = store.create_collection(name=body.name, description=body.description)

    record_event("rag_collection_created", {"collection_id": coll.collection_id, "name": coll.name})
    return CollectionResponse(
        collection_id=coll.collection_id,
        name=coll.name,
        description=coll.description,
        created_at=coll.created_at,
    )


@router.get("/api/rag/collections", response_model=List[CollectionResponse])
@limiter.limit("60/minute")
async def list_collections(request: Request, _auth=Depends(verify_api_key)):
    """List all document collections."""
    from rag_pipeline import VectorStore

    store = VectorStore.instance()
    collections = store.list_collections()
    return [
        CollectionResponse(
            collection_id=c.collection_id,
            name=c.name,
            description=c.description,
            created_at=c.created_at,
        )
        for c in collections
    ]


@router.delete("/api/rag/collections/{collection_id}")
@limiter.limit("20/minute")
async def delete_collection(
    request: Request,
    collection_id: str,
    _auth=Depends(verify_api_key),
):
    """Delete a document collection and all its documents."""
    from rag_pipeline import VectorStore

    store = VectorStore.instance()
    if not store.delete_collection(collection_id):
        raise ArchmorphException(404, "Collection not found")

    record_event("rag_collection_deleted", {"collection_id": collection_id})
    return {"status": "deleted", "collection_id": collection_id}


# ─────────────────────────────────────────────────────────────
# Document Endpoints
# ─────────────────────────────────────────────────────────────
@router.post(
    "/api/rag/collections/{collection_id}/ingest",
    response_model=IngestResponse,
)
@limiter.limit("10/minute")
async def ingest_document(
    request: Request,
    collection_id: str,
    file: UploadFile = File(...),
    chunk_size: int = Query(default=1024, ge=128, le=4096),
    chunk_overlap: int = Query(default=128, ge=0, le=512),
    _auth=Depends(verify_api_key),
):
    """Upload and ingest a document into a collection.

    Supports: PDF, DOCX, TXT, MD, HTML, CSV, JSON, YAML, XML, TF, Bicep
    """
    from rag_pipeline import SUPPORTED_EXTENSIONS, VectorStore, ingest_document as _ingest
    import os as _os

    store = VectorStore.instance()
    if store.get_collection(collection_id) is None:
        raise ArchmorphException(404, "Collection not found")

    # Validate filename
    if not file.filename:
        raise ArchmorphException(400, "Filename is required")

    ext = _os.path.splitext(file.filename.lower())[1]
    if ext not in SUPPORTED_EXTENSIONS:
        raise ArchmorphException(
            400,
            f"Unsupported file type: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    # Read file content with size limit
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise ArchmorphException(
            413,
            f"File too large. Maximum size: {MAX_UPLOAD_SIZE // (1024 * 1024)} MB",
        )

    if not content:
        raise ArchmorphException(400, "Uploaded file is empty")

    try:
        result = await asyncio.to_thread(
            _ingest,
            collection_id=collection_id,
            filename=file.filename,
            content=content,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            mime_type=file.content_type or "",
        )
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))
    except RuntimeError as exc:
        raise ArchmorphException(500, str(exc))

    record_event("rag_document_ingested", {
        "collection_id": collection_id,
        "filename": file.filename,
        "status": result.get("status"),
        "chunk_count": result.get("chunk_count", 0),
    })

    return IngestResponse(**result)


@router.get(
    "/api/rag/collections/{collection_id}/documents",
    response_model=List[DocumentResponse],
)
@limiter.limit("60/minute")
async def list_documents(
    request: Request,
    collection_id: str,
    _auth=Depends(verify_api_key),
):
    """List all documents in a collection."""
    from rag_pipeline import VectorStore

    store = VectorStore.instance()
    if store.get_collection(collection_id) is None:
        raise ArchmorphException(404, "Collection not found")

    docs = store.list_documents(collection_id)
    return [
        DocumentResponse(
            document_id=d.document_id,
            filename=d.filename,
            file_size=d.file_size,
            chunk_count=d.chunk_count,
            content_hash=d.content_hash,
            ingested_at=d.ingested_at,
            mime_type=d.mime_type,
        )
        for d in docs
    ]


@router.delete("/api/rag/collections/{collection_id}/documents/{document_id}")
@limiter.limit("20/minute")
async def remove_document(
    request: Request,
    collection_id: str,
    document_id: str,
    _auth=Depends(verify_api_key),
):
    """Remove a document from a collection."""
    from rag_pipeline import VectorStore

    store = VectorStore.instance()
    if not store.remove_document(collection_id, document_id):
        raise ArchmorphException(404, "Document or collection not found")

    record_event("rag_document_removed", {
        "collection_id": collection_id,
        "document_id": document_id,
    })
    return {"status": "deleted", "document_id": document_id}


# ─────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────
@router.post("/api/rag/search", response_model=SearchResponse)
@limiter.limit("30/minute")
async def search(
    request: Request,
    body: SearchRequest,
    _auth=Depends(verify_api_key),
):
    """Semantic search across document collections.

    Uses hybrid scoring (vector similarity + BM25 keyword matching).
    """
    from rag_pipeline import VectorStore

    store = VectorStore.instance()

    try:
        results = await asyncio.to_thread(
            store.search,
            query=body.query,
            collection_ids=body.collection_ids,
            top_k=body.top_k,
            min_score=body.min_score,
            metadata_filter=body.metadata_filter,
        )
    except Exception as exc:
        logger.error("RAG search failed: %s", exc, exc_info=True)
        raise ArchmorphException(500, "Search failed. Please try again.")

    record_event("rag_search", {
        "query_length": len(body.query),
        "result_count": len(results),
        "top_k": body.top_k,
    })

    return SearchResponse(
        results=[SearchResultItem(**r) for r in results],
        query=body.query,
        total_results=len(results),
    )


# ─────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────
@router.get(
    "/api/rag/collections/{collection_id}/stats",
    response_model=CollectionStats,
)
@limiter.limit("60/minute")
async def collection_stats(
    request: Request,
    collection_id: str,
    _auth=Depends(verify_api_key),
):
    """Get statistics for a document collection."""
    from rag_pipeline import VectorStore

    store = VectorStore.instance()
    stats = store.get_collection_stats(collection_id)
    if stats is None:
        raise ArchmorphException(404, "Collection not found")

    return CollectionStats(**stats)
