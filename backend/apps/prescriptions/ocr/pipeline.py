"""File bytes -> OcrResult. The OCR output is raw text only: it never approves anything."""
from .engines.base import OcrResult
from .errors import OcrError
from .pdf import render_pdf_pages
from .preprocess import preprocess


def run_ocr(data: bytes, kind: str, engine, *, max_pages: int = 3, pdf_renderer=render_pdf_pages) -> OcrResult:
    pages = pdf_renderer(data, max_pages) if kind == "pdf" else [data]
    if not pages:
        raise OcrError("No pages to read.")
    texts, lines = [], []
    for page in pages[:max_pages]:
        result = engine.recognize(preprocess(page))
        texts.append(result.text)
        lines.extend(result.lines)
    return OcrResult(text="\n\n".join(texts), lines=lines, engine=engine.name)
