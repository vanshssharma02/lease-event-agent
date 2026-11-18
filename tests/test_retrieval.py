"""Unit tests for Milestone 2: Chunking, ChromaDB vector indexing, and typed retrieval."""

from pathlib import Path
import pytest
import chromadb

from app.chunking import chunk_text, chunk_pdf, Chunk
from app.db import init_db
from app.seed import seed_database, get_leases_in_window
from app.retrieval import (
    get_chroma_client,
    get_or_create_collection,
    index_lease,
    index_all_in_window,
    retrieve,
    RetrievedLeaseContext,
)


@pytest.fixture
def temp_environment(tmp_path: Path):
    """Fixture providing isolated temporary database, data dir, and chroma dir."""
    db_file = tmp_path / "test_retrieval.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    seed_database(db_path=db_file, data_dir=data_dir)
    return db_file, data_dir, chroma_dir


def test_chunk_text_format_and_overlap():
    text = "The Tenant covenants to pay rent of £100,000 per annum on quarter days. " * 30
    chunks = chunk_text(text, lease_id="LSE-TEST-001", page=2, chunk_size=100, overlap=20)

    assert len(chunks) > 1
    for idx, c in enumerate(chunks, start=1):
        assert c.chunk_id == f"LSE-TEST-001-p2-c{idx}"
        assert c.lease_id == "LSE-TEST-001"
        assert c.page == 2
        assert c.token_count <= 100
        assert len(c.text) > 0


def test_chunk_pdf_extracts_all_pages(temp_environment):
    db_file, data_dir, _ = temp_environment
    pdf_path = data_dir / "LSE-EXP-001.pdf"
    assert pdf_path.exists()

    chunks = chunk_pdf(pdf_path, lease_id="LSE-EXP-001", chunk_size=400, overlap=50)
    assert len(chunks) >= 5

    # Check page sequence
    pages = [c.page for c in chunks]
    assert 1 in pages
    assert 5 in pages
    for c in chunks:
        assert c.chunk_id.startswith("LSE-EXP-001-p")
        assert c.token_count > 0


def test_chroma_indexing_and_metadata(temp_environment):
    db_file, data_dir, chroma_dir = temp_environment
    client = get_chroma_client(chroma_dir)
    pdf_path = data_dir / "LSE-BRK-002.pdf"

    count = index_lease("LSE-BRK-002", pdf_path, client=client, collection_name="test_col")
    assert count >= 5

    col = client.get_collection("test_col")
    res = col.get(where={"lease_id": "LSE-BRK-002"})
    assert len(res["ids"]) == count

    for meta in res["metadatas"]:
        assert meta["lease_id"] == "LSE-BRK-002"
        assert "page" in meta
        assert "chunk_id" in meta


def test_retrieve_typed_context_for_all_in_window_leases(temp_environment):
    db_file, data_dir, chroma_dir = temp_environment
    client = get_chroma_client(chroma_dir)
    index_all_in_window(db_path=db_file, client=client, collection_name="test_leases")

    in_window = get_leases_in_window(days=180, db_path=db_file)
    assert len(in_window) == 3

    for item in in_window:
        lid = item["lease_id"]
        ctx: RetrievedLeaseContext = retrieve(
            lease_id=lid,
            client=client,
            db_path=db_file,
            collection_name="test_leases",
        )

        assert ctx.lease.lease_id == lid
        assert ctx.lease.tenant == item["tenant"]
        assert ctx.lease.passing_rent == item["passing_rent"]
        assert ctx.lease.event_type == item["event_type"]
        assert len(ctx.chunks) >= 4

        combined_text = ctx.get_combined_text()
        # Verify key clauses are retrieved
        assert "RENT" in combined_text
        assert "BREAK" in combined_text
        assert "REINSTATEMENT" in combined_text

        # Verify citation metadata consistency
        for chunk in ctx.chunks:
            assert chunk.chunk_id.startswith(f"{lid}-p")
            assert chunk.page in range(1, 10)
            assert ctx.get_chunk_by_id(chunk.chunk_id) is not None


def test_retrieve_nonexistent_lease_raises(temp_environment):
    db_file, _, chroma_dir = temp_environment
    client = get_chroma_client(chroma_dir)

    with pytest.raises(ValueError, match="not found in lease_register"):
        retrieve("LSE-NONEXISTENT-999", client=client, db_path=db_file)
