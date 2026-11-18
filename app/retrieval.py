"""Retrieval and Vector Indexing Module.

Indexes chunked lease PDFs into local ChromaDB with metadata and exposes
typed retrieval combining vector search chunks with structured SQLite register records.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import chromadb
from chromadb.api.models.Collection import Collection

from app.config import settings
from app.db import get_connection
from app.chunking import chunk_pdf, Chunk


@dataclass(frozen=True)
class RetrievedChunk:
    """A retrieved chunk with source provenance and relevance info."""

    chunk_id: str
    lease_id: str
    page: int
    text: str
    score: Optional[float] = None
    topic: Optional[str] = None


@dataclass(frozen=True)
class LeaseRecord:
    """Structured fields from the SQLite lease and asset registers."""

    lease_id: str
    asset_id: str
    tenant: str
    expiry_date: str
    event_type: str
    passing_rent: float
    currency: str
    status: str
    asset_name: str
    holding_spv: str
    portfolio: str
    asset_manager: str
    doc_id: Optional[str] = None
    doc_path: Optional[str] = None


@dataclass
class RetrievedLeaseContext:
    """Combined typed context containing register data and retrieved document chunks."""

    lease: LeaseRecord
    chunks: List[RetrievedChunk] = field(default_factory=list)

    def get_chunk_by_id(self, chunk_id: str) -> Optional[RetrievedChunk]:
        """Lookup a specific chunk by its stable ID."""
        for c in self.chunks:
            if c.chunk_id == chunk_id:
                return c
        return None

    def get_all_chunk_ids(self) -> List[str]:
        """List all retrieved chunk IDs."""
        return [c.chunk_id for c in self.chunks]

    def get_combined_text(self) -> str:
        """Combine all chunk texts ordered by page."""
        sorted_chunks = sorted(self.chunks, key=lambda c: (c.page, c.chunk_id))
        return "\n\n---\n\n".join(
            f"[{c.chunk_id} | Page {c.page}]\n{c.text}" for c in sorted_chunks
        )


def get_chroma_client(persist_dir: Optional[Union[str, Path]] = None) -> chromadb.PersistentClient:
    """Instantiate a persistent ChromaDB client."""
    dir_path = Path(persist_dir) if persist_dir else settings.CHROMA_PERSIST_DIR
    dir_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(dir_path))


def get_or_create_collection(
    client: Optional[chromadb.PersistentClient] = None,
    collection_name: str = "lease_documents",
) -> Collection:
    """Retrieve or create the ChromaDB collection for lease documents."""
    if client is None:
        client = get_chroma_client()
    return client.get_or_create_collection(name=collection_name)


def index_lease(
    lease_id: str,
    pdf_path: Union[str, Path],
    client: Optional[chromadb.PersistentClient] = None,
    collection_name: str = "lease_documents",
) -> int:
    """Chunk a lease PDF and upsert all chunks into ChromaDB."""
    path = Path(pdf_path)
    chunks = chunk_pdf(path, lease_id=lease_id)
    if not chunks:
        return 0

    col = get_or_create_collection(client=client, collection_name=collection_name)

    ids = [c.chunk_id for c in chunks]
    documents = [c.text for c in chunks]
    metadatas = [
        {
            "lease_id": c.lease_id,
            "page": c.page,
            "chunk_id": c.chunk_id,
            "token_count": c.token_count,
        }
        for c in chunks
    ]

    col.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(chunks)


def index_all_in_window(
    db_path: Optional[Union[str, Path]] = None,
    client: Optional[chromadb.PersistentClient] = None,
    collection_name: str = "lease_documents",
) -> Dict[str, int]:
    """Index all documents associated with active leases in the database."""
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT lease_id, path FROM documents WHERE path IS NOT NULL;")
        rows = cur.fetchall()
    finally:
        conn.close()

    results: Dict[str, int] = {}
    for r in rows:
        lid = r["lease_id"]
        ppath = Path(r["path"])
        if ppath.exists():
            count = index_lease(lid, ppath, client=client, collection_name=collection_name)
            results[lid] = count
    return results


def retrieve(
    lease_id: str,
    client: Optional[chromadb.PersistentClient] = None,
    db_path: Optional[Union[str, Path]] = None,
    collection_name: str = "lease_documents",
) -> RetrievedLeaseContext:
    """Retrieve structured lease register data and relevant document chunks for a lease.

    Guarantees retrieval of chunks covering:
      - Term & Premises abstract
      - Passing rent & service charge cap
      - Rent review mechanism
      - Break clause & conditions
      - Reinstatement & dilapidations
    """
    # 1. Fetch structured register data from SQLite
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        query = """
            SELECT
                l.lease_id,
                l.asset_id,
                l.tenant,
                l.expiry_date,
                l.event_type,
                l.passing_rent,
                l.currency,
                l.status,
                a.asset_name,
                a.holding_spv,
                a.portfolio,
                a.asset_manager,
                d.doc_id,
                d.path AS doc_path
            FROM lease_register l
            JOIN asset_register a ON l.asset_id = a.asset_id
            LEFT JOIN documents d ON l.lease_id = d.lease_id
            WHERE l.lease_id = ?;
        """
        cur.execute(query, (lease_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Lease '{lease_id}' not found in lease_register.")

        lease_rec = LeaseRecord(
            lease_id=row["lease_id"],
            asset_id=row["asset_id"],
            tenant=row["tenant"],
            expiry_date=row["expiry_date"],
            event_type=row["event_type"],
            passing_rent=float(row["passing_rent"]),
            currency=row["currency"],
            status=row["status"],
            asset_name=row["asset_name"],
            holding_spv=row["holding_spv"],
            portfolio=row["portfolio"],
            asset_manager=row["asset_manager"],
            doc_id=row["doc_id"],
            doc_path=row["doc_path"],
        )
    finally:
        conn.close()

    # 2. Ensure chunks are indexed in ChromaDB
    col = get_or_create_collection(client=client, collection_name=collection_name)
    existing = col.get(where={"lease_id": lease_id})

    if not existing["ids"] and lease_rec.doc_path:
        pdf_path = Path(lease_rec.doc_path)
        if pdf_path.exists():
            index_lease(lease_id, pdf_path, client=client, collection_name=collection_name)
            existing = col.get(where={"lease_id": lease_id})

    # 3. Targeted semantic queries for core topics to compute relevance scores
    topic_queries = {
        "abstract": "demised premises lease term commencement expiry particulars",
        "rent": "passing rent annual rent payment terms service charge cap",
        "rent_review": "rent review mechanism open market review date RICS",
        "break_clause": "tenant break option break clause notice vacant possession arrears conditions",
        "reinstatement": "reinstatement obligations dilapidations estimate tenant covenants repair",
    }

    retrieved_map: Dict[str, RetrievedChunk] = {}

    for topic, q in topic_queries.items():
        try:
            res = col.query(
                query_texts=[q],
                n_results=2,
                where={"lease_id": lease_id},
            )
            if res["ids"] and res["ids"][0]:
                for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
                    if cid not in retrieved_map:
                        retrieved_map[cid] = RetrievedChunk(
                            chunk_id=cid,
                            lease_id=meta["lease_id"],
                            page=int(meta["page"]),
                            text=doc,
                            score=round(1.0 - float(dist), 4) if dist is not None else None,
                            topic=topic,
                        )
        except Exception:
            pass

    # Ensure all chunks for this lease are included so no critical clause is omitted
    all_chunks_res = col.get(where={"lease_id": lease_id})
    if all_chunks_res["ids"]:
        for cid, doc, meta in zip(all_chunks_res["ids"], all_chunks_res["documents"], all_chunks_res["metadatas"]):
            if cid not in retrieved_map:
                retrieved_map[cid] = RetrievedChunk(
                    chunk_id=cid,
                    lease_id=meta["lease_id"],
                    page=int(meta["page"]),
                    text=doc,
                    score=1.0,
                    topic="general",
                )

    # Sort deterministically by page then chunk_id
    sorted_chunks = sorted(retrieved_map.values(), key=lambda c: (c.page, c.chunk_id))
    return RetrievedLeaseContext(lease=lease_rec, chunks=sorted_chunks)
