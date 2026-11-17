"""Render the first pages of a PDF to PNG bytes (PyMuPDF, imported lazily)."""
from .errors import OcrError, OcrUnavailable


def render_pdf_pages(data: bytes, max_pages: int = 3, dpi: int = 200) -> list:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise OcrUnavailable("PyMuPDF is not installed, so PDFs cannot be read automatically.") from exc
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            if doc.needs_pass:
                raise OcrError("The PDF is password protected.")
            return [doc[i].get_pixmap(dpi=dpi).tobytes("png") for i in range(min(len(doc), max_pages))]
        finally:
            doc.close()
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError("The PDF could not be read.") from exc
