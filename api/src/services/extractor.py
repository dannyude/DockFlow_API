"""Document text-extraction adapters for supported file formats."""

import io

import docx
import pypdf
import pytesseract
from PIL import Image


def extract_text(file_bytes: bytes, mime_type: str) -> str:
    """Dispatch extraction by MIME type and return normalized text."""
    if mime_type == "application/pdf":
        return _extract_pdf(file_bytes)
    if mime_type in {"image/png", "image/jpeg", "image/tiff"}:
        return _extract_image_ocr(file_bytes)
    if "wordprocessingml" in mime_type:
        return _extract_docx(file_bytes)
    raise ValueError(f"Unsupported mime type: {mime_type}")


def _extract_pdf(data: bytes) -> str:
    """Extract text from all pages in a PDF payload."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    return " ".join(page.extract_text() or "" for page in reader.pages)


def _extract_image_ocr(data: bytes) -> str:
    """Run OCR over image bytes and return recognized text."""
    image = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(image)


def _extract_docx(data: bytes) -> str:
    """Extract paragraph text from a DOCX document payload."""
    document = docx.Document(io.BytesIO(data))
    return " ".join(paragraph.text for paragraph in document.paragraphs)
