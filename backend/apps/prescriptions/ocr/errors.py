class OcrUnavailable(Exception):
    """An OCR dependency (OpenCV, Tesseract, PyMuPDF) is not installed or not found."""


class OcrError(Exception):
    """OCR ran but failed for this file (unreadable image, timeout, ...)."""
