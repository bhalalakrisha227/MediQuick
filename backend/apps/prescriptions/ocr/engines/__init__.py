from .base import OcrEngine, OcrResult
from .tesseract import TesseractEngine


def get_engine(name: str, *, cmd: str = "", lang: str = "eng", timeout: int = 60) -> OcrEngine:
    """Engine factory. Add 'paddle' here later without touching the rest of the pipeline."""
    if name == "tesseract":
        return TesseractEngine(cmd=cmd, lang=lang, timeout=timeout)
    raise ValueError(f"Unknown OCR engine: {name}")
