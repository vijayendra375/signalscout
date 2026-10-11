"""PDF document and annual report parser."""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional
from pypdf import PdfReader


class ParsedPdf:
    def __init__(self, pages_text: List[str], metadata: Dict[str, Any], total_pages: int) -> None:
        self.pages_text = pages_text
        self.metadata = metadata
        self.total_pages = total_pages

    @property
    def full_text(self) -> str:
        return "\n\n".join(self.pages_text)


def parse_pdf_document(content_bytes: bytes) -> ParsedPdf:
    """Extract page text and document metadata from raw PDF bytes."""
    pages_text: List[str] = []
    metadata: Dict[str, Any] = {}
    
    try:
        reader = PdfReader(io.BytesIO(content_bytes))
        total_pages = len(reader.pages)
        if reader.metadata:
            metadata = {k: str(v) for k, v in reader.metadata.items()}
            
        for page in reader.pages:
            extracted = page.extract_text() or ""
            pages_text.append(extracted.strip())
            
        return ParsedPdf(pages_text=pages_text, metadata=metadata, total_pages=total_pages)
    except Exception as e:
        return ParsedPdf(pages_text=[], metadata={"error": str(e)}, total_pages=0)
