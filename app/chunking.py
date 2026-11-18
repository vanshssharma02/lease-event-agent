"""PDF Token-based Chunking Module.

Splits PDF text by token count (~400 tokens, 50 overlap), preserving page numbers
and generating deterministic, stable chunk IDs in the format '{lease_id}-p{page}-c{n}'.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Union
import fitz
import tiktoken


@dataclass(frozen=True)
class Chunk:
    """Represents a token-bounded slice of document text with source provenance."""

    chunk_id: str
    lease_id: str
    page: int
    text: str
    token_count: int


def get_tokenizer(encoding_name: str = "cl100k_base") -> tiktoken.Encoding:
    """Retrieve or cache a tiktoken encoding."""
    try:
        return tiktoken.get_encoding(encoding_name)
    except Exception:
        # Fallback to cl100k_base if custom encoding unavailable
        return tiktoken.get_encoding("cl100k_base")


def chunk_text(
    text: str,
    lease_id: str,
    page: int,
    chunk_size: int = 400,
    overlap: int = 50,
    encoding_name: str = "cl100k_base",
) -> List[Chunk]:
    """Split text on a single page by token count with sliding window overlap.

    Produces stable chunk IDs: '{lease_id}-p{page}-c{n}' where n is 1-indexed.
    """
    clean_text = text.strip()
    if not clean_text:
        return []

    enc = get_tokenizer(encoding_name)
    tokens = enc.encode(clean_text)

    if not tokens:
        return []

    # If the text fits comfortably inside one chunk, return immediately
    if len(tokens) <= chunk_size:
        return [
            Chunk(
                chunk_id=f"{lease_id}-p{page}-c1",
                lease_id=lease_id,
                page=page,
                text=clean_text,
                token_count=len(tokens),
            )
        ]

    chunks: List[Chunk] = []
    step = max(1, chunk_size - overlap)
    chunk_index = 1

    start_idx = 0
    total_tokens = len(tokens)

    while start_idx < total_tokens:
        end_idx = min(start_idx + chunk_size, total_tokens)
        chunk_token_slice = tokens[start_idx:end_idx]
        chunk_str = enc.decode(chunk_token_slice).strip()

        if chunk_str:
            chunk_id = f"{lease_id}-p{page}-c{chunk_index}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    lease_id=lease_id,
                    page=page,
                    text=chunk_str,
                    token_count=len(chunk_token_slice),
                )
            )
            chunk_index += 1

        if end_idx >= total_tokens:
            break
        start_idx += step

    return chunks


def chunk_pdf(
    pdf_path: Union[str, Path],
    lease_id: str,
    chunk_size: int = 400,
    overlap: int = 50,
) -> List[Chunk]:
    """Extract and token-chunk text from a multi-page PDF document.

    Maintains 1-based page numbering across all pages.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF document not found at: {path}")

    all_chunks: List[Chunk] = []
    doc = fitz.open(path)
    try:
        for page_idx in range(doc.page_count):
            page_num = page_idx + 1
            page_text = doc[page_idx].get_text()
            page_chunks = chunk_text(
                text=page_text,
                lease_id=lease_id,
                page=page_num,
                chunk_size=chunk_size,
                overlap=overlap,
            )
            all_chunks.extend(page_chunks)
    finally:
        doc.close()

    return all_chunks
