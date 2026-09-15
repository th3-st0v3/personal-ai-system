"""Extract text from PDFs before sending it through the normal source ingestion pipeline."""
from __future__ import annotations

from io import BytesIO


def extract_pdf_pages(data: bytes) -> list[str]:
    if not data:
        raise ValueError("PDF is empty.")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency installation is exercised by CI
        raise RuntimeError("PDF support requires the pypdf package.") from exc
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise ValueError("The uploaded file is not a readable PDF.") from exc
    pages: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        pages.append(text)
    if not any(pages):
        raise ValueError("No extractable text was found in the PDF. Scanned/image-only PDFs require OCR and are not supported yet.")
    return pages


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    pages = extract_pdf_pages(data)
    chunks = [f"[Page {index}]\n{text}" for index, text in enumerate(pages, start=1) if text]
    return "\n\n".join(chunks), len(pages)


__all__ = ["extract_pdf_pages", "extract_pdf_text"]
