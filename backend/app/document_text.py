from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


class DocumentExtractionError(ValueError):
    """A permanent, user-actionable failure to extract an uploaded document."""


def validate_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise DocumentExtractionError("Only .pdf, .docx, .txt and .md files are supported")
    return suffix


def extract_text(filename: str, data: bytes) -> str:
    suffix = validate_filename(filename)

    if suffix == ".pdf":
        text = _extract_pdf(data)
    elif suffix == ".docx":
        text = _extract_docx(data)
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentExtractionError("Text files must be UTF-8 encoded") from exc

    text = text.strip()
    if not text:
        raise DocumentExtractionError("Document contains no extractable text")
    return text


def _extract_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise DocumentExtractionError("Encrypted PDF files are not supported")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError("PDF file is damaged or cannot be parsed") from exc


def _extract_docx(data: bytes) -> str:
    try:
        document = DocxDocument(BytesIO(data))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    except Exception as exc:
        raise DocumentExtractionError("DOCX file is damaged or cannot be parsed") from exc
