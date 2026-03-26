"""
Document parsing layer.
Handles PDF and DOCX files, extracts clean text.
"""
import io
from pathlib import Path


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from PDF or DOCX file bytes."""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return _parse_pdf(file_bytes)
    elif ext in (".docx", ".doc"):
        return _parse_docx(file_bytes)
    elif ext == ".txt":
        return file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: {ext}. Use PDF, DOCX, or TXT.")


def _parse_pdf(file_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    return "\n\n".join(pages)


def _parse_docx(file_bytes: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def chunk_into_clauses(text: str, max_chunk: int = 800) -> list[str]:
    """
    Split contract text into clause-sized chunks for RAG comparison.
    Tries to split on numbered headings first, then falls back to paragraphs.
    """
    import re

    # Try to split on clause headers like "1.", "2.1", "SECTION 1", etc.
    clause_pattern = re.compile(
        r'(?=(?:\n|^)(?:\d+\.[\d.]*\s|\bSECTION\s+\d+|\bARTICLE\s+\d+|\b[A-Z]{3,}\s*\n))',
        re.MULTILINE
    )
    chunks = clause_pattern.split(text)
    chunks = [c.strip() for c in chunks if c.strip()]

    if len(chunks) <= 1:
        # Fallback: split by double newlines (paragraphs)
        chunks = [c.strip() for c in text.split("\n\n") if c.strip()]

    # Merge very short chunks and split very long ones
    result = []
    current = ""
    for chunk in chunks:
        if len(current) + len(chunk) < max_chunk:
            current += "\n\n" + chunk if current else chunk
        else:
            if current:
                result.append(current)
            current = chunk
    if current:
        result.append(current)

    return result
