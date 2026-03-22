"""
Archmorph RAG Pipeline — Retrieval-Augmented Generation engine.

Provides document parsing, chunking, embedding, in-memory vector search,
and hybrid retrieval (vector + BM25) so that HLD/IaC generators can
reference user-uploaded compliance docs, runbooks, and architecture
reference materials.

Issue #395 — Track 1 Product Value feature.
"""

import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from openai_client import get_openai_client, openai_retry

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
EMBEDDING_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
)
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
DEFAULT_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1024"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "128"))
DEFAULT_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
MAX_BATCH_SIZE = 16  # Azure OpenAI batch limit per request

# BM25 weight in hybrid scoring (0.0 = pure vector, 1.0 = pure BM25)
BM25_WEIGHT = float(os.getenv("RAG_BM25_WEIGHT", "0.3"))


# ─────────────────────────────────────────────────────────────
# Token counting
# ─────────────────────────────────────────────────────────────
_tokenizer = None
_tokenizer_lock = threading.Lock()


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer
    with _tokenizer_lock:
        if _tokenizer is not None:
            return _tokenizer
        try:
            import tiktoken
            _tokenizer = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            logger.warning("tiktoken not installed — falling back to word-based estimation")
            _tokenizer = None
    return _tokenizer


def count_tokens(text: str) -> int:
    enc = _get_tokenizer()
    if enc is not None:
        return len(enc.encode(text))
    # Rough fallback: ~4 chars per token for English
    return max(1, len(text) // 4)


# ─────────────────────────────────────────────────────────────
# Document Parsing
# ─────────────────────────────────────────────────────────────
def parse_pdf(content: bytes) -> List[Dict[str, Any]]:
    """Extract text from a PDF file, returning pages with metadata."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is required for PDF parsing. Install with: pip install pdfplumber")

    pages: List[Dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append({"text": text, "page": i + 1})
    return pages


def parse_docx(content: bytes) -> List[Dict[str, Any]]:
    """Extract text from a DOCX file."""
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError("python-docx is required for DOCX parsing. Install with: pip install python-docx")

    doc = Document(io.BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return [{"text": "\n".join(paragraphs), "page": 1}]


def parse_html(content: bytes) -> List[Dict[str, Any]]:
    """Strip HTML tags and extract text."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("beautifulsoup4 is required for HTML parsing. Install with: pip install beautifulsoup4")

    soup = BeautifulSoup(content, "html.parser")
    # Remove script and style elements
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return [{"text": text, "page": 1}]


def parse_csv_file(content: bytes) -> List[Dict[str, Any]]:
    """Convert CSV rows into text."""
    text_content = content.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text_content))
    rows = list(reader)
    if not rows:
        return []
    # Format as header: value pairs if we have a header row
    header = rows[0]
    lines = []
    for row in rows[1:]:
        parts = [f"{header[i]}: {row[i]}" for i in range(min(len(header), len(row))) if row[i].strip()]
        if parts:
            lines.append("; ".join(parts))
    if not lines:
        # Fallback: just dump all rows
        lines = [", ".join(row) for row in rows if any(c.strip() for c in row)]
    return [{"text": "\n".join(lines), "page": 1}]


def parse_json_file(content: bytes) -> List[Dict[str, Any]]:
    """Convert JSON to readable text."""
    text_content = content.decode("utf-8", errors="replace")
    data = json.loads(text_content)
    formatted = json.dumps(data, indent=2, ensure_ascii=False)
    return [{"text": formatted, "page": 1}]


def parse_text(content: bytes) -> List[Dict[str, Any]]:
    """Read plain text / markdown files."""
    text = content.decode("utf-8", errors="replace")
    return [{"text": text, "page": 1}]


# Dispatcher mapping file extension → parser
PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".html": parse_html,
    ".htm": parse_html,
    ".csv": parse_csv_file,
    ".json": parse_json_file,
    ".txt": parse_text,
    ".md": parse_text,
    ".markdown": parse_text,
    ".rst": parse_text,
    ".yaml": parse_text,
    ".yml": parse_text,
    ".xml": parse_text,
    ".tf": parse_text,
    ".bicep": parse_text,
}

SUPPORTED_EXTENSIONS = set(PARSERS.keys())


def parse_document(filename: str, content: bytes) -> List[Dict[str, Any]]:
    """Parse a document by extension, returning list of {text, page} dicts."""
    ext = os.path.splitext(filename.lower())[1]
    parser = PARSERS.get(ext)
    if parser is None:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    return parser(content)


# ─────────────────────────────────────────────────────────────
# Chunking Engine
# ─────────────────────────────────────────────────────────────
@dataclass
class Chunk:
    """A retrieval-ready text chunk with source metadata."""
    text: str
    chunk_index: int
    source_document: str
    document_id: str
    page: int = 1
    token_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "chunk_index": self.chunk_index,
            "source_document": self.source_document,
            "document_id": self.document_id,
            "page": self.page,
            "token_count": self.token_count,
        }


def _split_text_recursive(text: str, max_tokens: int) -> List[str]:
    """Recursively split text using hierarchy of separators."""
    separators = ["\n\n", "\n", ". ", " "]
    if count_tokens(text) <= max_tokens:
        return [text]

    for sep in separators:
        parts = text.split(sep)
        if len(parts) <= 1:
            continue

        chunks = []
        current = ""
        for part in parts:
            candidate = current + sep + part if current else part
            if count_tokens(candidate) > max_tokens and current:
                chunks.append(current)
                current = part
            else:
                current = candidate
        if current:
            chunks.append(current)
        if len(chunks) > 1:
            result = []
            for c in chunks:
                result.extend(_split_text_recursive(c, max_tokens))
            return result

    # Last resort: hard split by characters
    result = []
    words = text.split()
    current = ""
    for word in words:
        candidate = current + " " + word if current else word
        if count_tokens(candidate) > max_tokens and current:
            result.append(current)
            current = word
        else:
            current = candidate
    if current:
        result.append(current)
    return result


def chunk_document(
    pages: List[Dict[str, Any]],
    filename: str,
    document_id: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[Chunk]:
    """Split parsed pages into overlapping chunks.

    Uses sliding window with recursive splitting as fallback.
    """
    chunks: List[Chunk] = []
    chunk_idx = 0

    for page_data in pages:
        text = page_data["text"]
        page_num = page_data.get("page", 1)

        segments = _split_text_recursive(text, chunk_size)

        for i, segment in enumerate(segments):
            segment = segment.strip()
            if not segment:
                continue

            chunks.append(Chunk(
                text=segment,
                chunk_index=chunk_idx,
                source_document=filename,
                document_id=document_id,
                page=page_num,
                token_count=count_tokens(segment),
            ))
            chunk_idx += 1

            # Create overlap chunk if not last segment and overlap > 0
            if chunk_overlap > 0 and i < len(segments) - 1:
                next_seg = segments[i + 1].strip()
                if not next_seg:
                    continue
                # Take the tail of current + head of next for overlap
                overlap_tokens = chunk_overlap
                current_words = segment.split()
                next_words = next_seg.split()
                # Approximate overlap by words (rough ~1.3 tokens/word)
                overlap_word_count = max(1, overlap_tokens // 2)
                tail = " ".join(current_words[-overlap_word_count:]) if len(current_words) > overlap_word_count else segment
                head = " ".join(next_words[:overlap_word_count]) if len(next_words) > overlap_word_count else next_seg
                overlap_text = tail + " " + head
                if count_tokens(overlap_text) > 10:  # Don't create tiny overlap chunks
                    chunks.append(Chunk(
                        text=overlap_text,
                        chunk_index=chunk_idx,
                        source_document=filename,
                        document_id=document_id,
                        page=page_num,
                        token_count=count_tokens(overlap_text),
                    ))
                    chunk_idx += 1

    return chunks


# ─────────────────────────────────────────────────────────────
# Embedding Pipeline
# ─────────────────────────────────────────────────────────────
_embedding_cache: Dict[str, np.ndarray] = {}
_embedding_cache_lock = threading.Lock()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@openai_retry
def _embed_batch(texts: List[str]) -> List[np.ndarray]:
    """Call Azure OpenAI embeddings API for a batch of texts."""
    client = get_openai_client()
    response = client.embeddings.create(
        input=texts,
        model=EMBEDDING_DEPLOYMENT,
    )
    return [np.array(item.embedding, dtype=np.float32) for item in response.data]


def embed_texts(texts: List[str]) -> List[np.ndarray]:
    """Generate embeddings with caching and batching.

    Skips re-embedding for texts whose content hash is already cached.
    """
    results: List[Optional[np.ndarray]] = [None] * len(texts)
    to_embed: List[Tuple[int, str]] = []

    with _embedding_cache_lock:
        for i, text in enumerate(texts):
            h = _content_hash(text)
            if h in _embedding_cache:
                results[i] = _embedding_cache[h]
            else:
                to_embed.append((i, text))

    if not to_embed:
        return results  # type: ignore[return-value]

    # Batch embed uncached texts
    for batch_start in range(0, len(to_embed), MAX_BATCH_SIZE):
        batch = to_embed[batch_start:batch_start + MAX_BATCH_SIZE]
        batch_texts = [t for _, t in batch]
        embeddings = _embed_batch(batch_texts)

        with _embedding_cache_lock:
            for (orig_idx, text), emb in zip(batch, embeddings):
                h = _content_hash(text)
                _embedding_cache[h] = emb
                results[orig_idx] = emb

    return results  # type: ignore[return-value]


def embed_single(text: str) -> np.ndarray:
    """Embed a single text string."""
    return embed_texts([text])[0]


# ─────────────────────────────────────────────────────────────
# BM25 Scoring (lightweight implementation)
# ─────────────────────────────────────────────────────────────
def _tokenize_for_bm25(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer for BM25."""
    return re.findall(r'\w+', text.lower())


class BM25Index:
    """Okapi BM25 scoring for keyword-based retrieval."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus: List[List[str]] = []
        self.doc_len: List[int] = []
        self.avgdl: float = 0.0
        self.idf: Dict[str, float] = {}
        self.doc_freq: Dict[str, int] = {}
        self.n_docs: int = 0

    def build(self, documents: List[str]):
        """Build the BM25 index from a list of documents."""
        self.corpus = [_tokenize_for_bm25(doc) for doc in documents]
        self.doc_len = [len(d) for d in self.corpus]
        self.n_docs = len(self.corpus)
        self.avgdl = sum(self.doc_len) / max(self.n_docs, 1)

        # Compute document frequency
        self.doc_freq = {}
        for doc_tokens in self.corpus:
            seen = set(doc_tokens)
            for token in seen:
                self.doc_freq[token] = self.doc_freq.get(token, 0) + 1

        # Compute IDF
        self.idf = {}
        for token, df in self.doc_freq.items():
            self.idf[token] = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query: str) -> List[float]:
        """Score all documents against a query."""
        query_tokens = _tokenize_for_bm25(query)
        scores = [0.0] * self.n_docs

        for token in query_tokens:
            if token not in self.idf:
                continue
            idf = self.idf[token]
            for i, doc_tokens in enumerate(self.corpus):
                tf = doc_tokens.count(token)
                dl = self.doc_len[i]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1))
                scores[i] += idf * numerator / max(denominator, 1e-9)

        return scores


# ─────────────────────────────────────────────────────────────
# Vector Store — In-memory with cosine similarity
# ─────────────────────────────────────────────────────────────
@dataclass
class StoredChunk:
    """A chunk stored in the vector store with its embedding."""
    chunk: Chunk
    embedding: np.ndarray


@dataclass
class DocumentRecord:
    """Metadata for an ingested document."""
    document_id: str
    filename: str
    file_size: int
    chunk_count: int
    content_hash: str
    ingested_at: str
    mime_type: str = ""


@dataclass
class Collection:
    """A named collection of document chunks with their embeddings."""
    collection_id: str
    name: str
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    chunks: List[StoredChunk] = field(default_factory=list)
    documents: Dict[str, DocumentRecord] = field(default_factory=dict)
    bm25_index: Optional[BM25Index] = field(default=None, repr=False)

    def rebuild_bm25(self):
        """Rebuild BM25 index from current chunks."""
        if not self.chunks:
            self.bm25_index = None
            return
        texts = [sc.chunk.text for sc in self.chunks]
        idx = BM25Index()
        idx.build(texts)
        self.bm25_index = idx

    @property
    def total_tokens(self) -> int:
        return sum(sc.chunk.token_count for sc in self.chunks)


class VectorStore:
    """Thread-safe in-memory vector store with cosine similarity search.

    Singleton pattern — use VectorStore.instance() to get the shared store.
    """

    _instance: Optional["VectorStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._collections: Dict[str, Collection] = {}
        self._lock = threading.RLock()

    @classmethod
    def instance(cls) -> "VectorStore":
        if cls._instance is not None:
            return cls._instance
        with cls._instance_lock:
            if cls._instance is not None:
                return cls._instance
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset the singleton (for testing)."""
        with cls._instance_lock:
            cls._instance = None

    # ── Collection management ──

    def create_collection(self, name: str, description: str = "") -> Collection:
        with self._lock:
            collection_id = str(uuid.uuid4())
            coll = Collection(collection_id=collection_id, name=name, description=description)
            self._collections[collection_id] = coll
            logger.info("Created collection %s (%s)", name, collection_id)
            return coll

    def get_collection(self, collection_id: str) -> Optional[Collection]:
        with self._lock:
            return self._collections.get(collection_id)

    def list_collections(self) -> List[Collection]:
        with self._lock:
            return list(self._collections.values())

    def delete_collection(self, collection_id: str) -> bool:
        with self._lock:
            if collection_id in self._collections:
                del self._collections[collection_id]
                logger.info("Deleted collection %s", collection_id)
                return True
            return False

    # ── Document management ──

    def add_document(
        self,
        collection_id: str,
        document_id: str,
        filename: str,
        chunks: List[Chunk],
        embeddings: List[np.ndarray],
        file_size: int,
        content_hash: str,
        mime_type: str = "",
    ) -> DocumentRecord:
        with self._lock:
            coll = self._collections.get(collection_id)
            if coll is None:
                raise ValueError(f"Collection {collection_id} not found")

            # Check for duplicate content
            for doc in coll.documents.values():
                if doc.content_hash == content_hash:
                    logger.info("Document with same content already exists: %s", doc.document_id)
                    return doc

            # Store chunks with embeddings
            for chunk, emb in zip(chunks, embeddings):
                coll.chunks.append(StoredChunk(chunk=chunk, embedding=emb))

            # Record document metadata
            record = DocumentRecord(
                document_id=document_id,
                filename=filename,
                file_size=file_size,
                chunk_count=len(chunks),
                content_hash=content_hash,
                ingested_at=datetime.now(timezone.utc).isoformat(),
                mime_type=mime_type,
            )
            coll.documents[document_id] = record

            # Rebuild BM25 index
            coll.rebuild_bm25()

            logger.info(
                "Added document %s (%s) to collection %s: %d chunks",
                filename, document_id, collection_id, len(chunks),
            )
            return record

    def remove_document(self, collection_id: str, document_id: str) -> bool:
        with self._lock:
            coll = self._collections.get(collection_id)
            if coll is None:
                return False
            if document_id not in coll.documents:
                return False

            # Remove chunks belonging to this document
            coll.chunks = [sc for sc in coll.chunks if sc.chunk.document_id != document_id]
            del coll.documents[document_id]

            # Rebuild BM25 index
            coll.rebuild_bm25()

            logger.info("Removed document %s from collection %s", document_id, collection_id)
            return True

    def list_documents(self, collection_id: str) -> List[DocumentRecord]:
        with self._lock:
            coll = self._collections.get(collection_id)
            if coll is None:
                return []
            return list(coll.documents.values())

    def get_collection_stats(self, collection_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            coll = self._collections.get(collection_id)
            if coll is None:
                return None
            return {
                "collection_id": coll.collection_id,
                "name": coll.name,
                "description": coll.description,
                "created_at": coll.created_at,
                "document_count": len(coll.documents),
                "chunk_count": len(coll.chunks),
                "total_tokens": coll.total_tokens,
            }

    # ── Search ──

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def search(
        self,
        query: str,
        collection_ids: Optional[List[str]] = None,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = 0.0,
        metadata_filter: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Hybrid search combining vector similarity and BM25 scoring.

        Args:
            query: Natural language search query
            collection_ids: Restrict search to these collections (None = all)
            top_k: Number of results to return
            min_score: Minimum combined score threshold
            metadata_filter: Filter by source_document name (optional)

        Returns:
            List of search results with chunk data, scores, and citations.
        """
        query_embedding = embed_single(query)

        with self._lock:
            # Gather target collections
            if collection_ids:
                collections = [
                    self._collections[cid]
                    for cid in collection_ids
                    if cid in self._collections
                ]
            else:
                collections = list(self._collections.values())

            all_results: List[Dict[str, Any]] = []

            for coll in collections:
                if not coll.chunks:
                    continue

                # Apply metadata filter
                filtered_indices = []
                for i, sc in enumerate(coll.chunks):
                    if metadata_filter:
                        match = True
                        if "source_document" in metadata_filter:
                            if metadata_filter["source_document"].lower() not in sc.chunk.source_document.lower():
                                match = False
                        if not match:
                            continue
                    filtered_indices.append(i)

                if not filtered_indices:
                    continue

                # Vector similarity scores
                embeddings_matrix = np.array([coll.chunks[i].embedding for i in filtered_indices])
                similarities = np.dot(embeddings_matrix, query_embedding) / (
                    np.linalg.norm(embeddings_matrix, axis=1) * np.linalg.norm(query_embedding) + 1e-9
                )

                # BM25 scores (if available)
                bm25_scores_all = None
                if coll.bm25_index is not None:
                    bm25_scores_all = coll.bm25_index.score(query)

                for rank, idx in enumerate(filtered_indices):
                    vec_score = float(similarities[rank])

                    bm25_score = 0.0
                    if bm25_scores_all is not None:
                        bm25_score = bm25_scores_all[idx]

                    # Normalize BM25 to [0, 1] range approximately
                    # (max BM25 across this collection for normalization)
                    bm25_max = max(bm25_scores_all) if bm25_scores_all and max(bm25_scores_all) > 0 else 1.0
                    bm25_normalized = bm25_score / bm25_max if bm25_max > 0 else 0.0

                    combined_score = (1 - BM25_WEIGHT) * vec_score + BM25_WEIGHT * bm25_normalized

                    if combined_score < min_score:
                        continue

                    sc = coll.chunks[idx]
                    all_results.append({
                        "text": sc.chunk.text,
                        "score": round(combined_score, 4),
                        "vector_score": round(vec_score, 4),
                        "bm25_score": round(bm25_normalized, 4),
                        "source_document": sc.chunk.source_document,
                        "document_id": sc.chunk.document_id,
                        "page": sc.chunk.page,
                        "chunk_index": sc.chunk.chunk_index,
                        "collection_id": coll.collection_id,
                        "collection_name": coll.name,
                    })

        # Sort by combined score descending, return top_k
        all_results.sort(key=lambda r: r["score"], reverse=True)
        return all_results[:top_k]


# ─────────────────────────────────────────────────────────────
# Context Assembly — for HLD/IaC generators
# ─────────────────────────────────────────────────────────────
def assemble_context(
    query: str,
    collection_ids: Optional[List[str]] = None,
    top_k: int = DEFAULT_TOP_K,
    max_tokens: int = 4000,
) -> Dict[str, Any]:
    """Search and assemble RAG context for use by generators.

    Returns a dict with:
        - context_text: concatenated relevant chunks (token-limited)
        - citations: list of source references
        - chunk_count: how many chunks were included
    """
    store = VectorStore.instance()
    results = store.search(query=query, collection_ids=collection_ids, top_k=top_k)

    if not results:
        return {"context_text": "", "citations": [], "chunk_count": 0}

    context_parts: List[str] = []
    citations: List[Dict[str, Any]] = []
    total_tokens = 0

    for r in results:
        chunk_tokens = count_tokens(r["text"])
        if total_tokens + chunk_tokens > max_tokens:
            break
        context_parts.append(
            f"[Source: {r['source_document']}, Page {r['page']}]\n{r['text']}"
        )
        citations.append({
            "source_document": r["source_document"],
            "document_id": r["document_id"],
            "page": r["page"],
            "score": r["score"],
            "collection_name": r["collection_name"],
        })
        total_tokens += chunk_tokens

    return {
        "context_text": "\n\n---\n\n".join(context_parts),
        "citations": citations,
        "chunk_count": len(context_parts),
    }


# ─────────────────────────────────────────────────────────────
# Full Ingestion Pipeline
# ─────────────────────────────────────────────────────────────
def ingest_document(
    collection_id: str,
    filename: str,
    content: bytes,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    mime_type: str = "",
) -> Dict[str, Any]:
    """End-to-end document ingestion: parse → chunk → embed → store.

    Returns document metadata and ingestion stats.
    """
    store = VectorStore.instance()

    coll = store.get_collection(collection_id)
    if coll is None:
        raise ValueError(f"Collection {collection_id} not found")

    document_id = str(uuid.uuid4())
    content_hash = hashlib.sha256(content).hexdigest()

    # Check duplicate
    for doc in coll.documents.values():
        if doc.content_hash == content_hash:
            return {
                "document_id": doc.document_id,
                "filename": doc.filename,
                "status": "duplicate",
                "message": "Document with identical content already exists",
                "chunk_count": doc.chunk_count,
            }

    # Parse
    pages = parse_document(filename, content)
    if not pages:
        return {
            "document_id": document_id,
            "filename": filename,
            "status": "empty",
            "message": "No text content extracted from document",
            "chunk_count": 0,
        }

    # Chunk
    chunks = chunk_document(pages, filename, document_id, chunk_size, chunk_overlap)
    if not chunks:
        return {
            "document_id": document_id,
            "filename": filename,
            "status": "empty",
            "message": "Chunking produced no chunks",
            "chunk_count": 0,
        }

    # Embed
    chunk_texts = [c.text for c in chunks]
    embeddings = embed_texts(chunk_texts)

    # Store
    record = store.add_document(
        collection_id=collection_id,
        document_id=document_id,
        filename=filename,
        chunks=chunks,
        embeddings=embeddings,
        file_size=len(content),
        content_hash=content_hash,
        mime_type=mime_type,
    )

    return {
        "document_id": record.document_id,
        "filename": record.filename,
        "status": "ingested",
        "chunk_count": record.chunk_count,
        "file_size": record.file_size,
        "content_hash": record.content_hash,
    }
