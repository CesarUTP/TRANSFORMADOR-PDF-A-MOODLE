"""
extractor.py — Handles text extraction from uploaded files.
Supports .pdf (via pdfplumber) and .txt (direct UTF-8 read).
"""
import pdfplumber
import io


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF file given its raw bytes."""
    full_text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
    return full_text


def extract_text_from_txt(file_bytes: bytes) -> str:
    """Decode a text file from raw bytes (UTF-8 with fallback to latin-1)."""
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1")
