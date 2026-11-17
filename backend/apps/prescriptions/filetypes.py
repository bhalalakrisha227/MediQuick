"""
Upload validation by file CONTENT, never by file name or the browser's claimed type.

Accepts JPEG, PNG and PDF only. Pure Python (no Pillow/OpenCV) so a hostile file is
rejected before any image library touches it. Best-effort checks, not a virus scanner.
"""
import re
from dataclasses import dataclass

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
# Active/embedded content we refuse inside PDFs (best effort: obfuscated PDFs can evade a byte search).
_PDF_ACTIVE = re.compile(rb"/(JavaScript|JS|Launch|EmbeddedFile|RichMedia)(?![A-Za-z0-9])")


class UploadRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class FileInfo:
    kind: str          # "jpeg" | "png" | "pdf"
    ext: str           # "jpg" | "png" | "pdf"
    content_type: str
    width: int | None
    height: int | None


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(PNG_SIGNATURE):
        return "png"
    if data.startswith(b"%PDF-"):
        return "pdf"
    return None


def _png_dimensions(data: bytes):
    # First chunk must be IHDR: 8 sig + 4 length + 4 "IHDR" + 4 width + 4 height
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _jpeg_dimensions(data: bytes):
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:            # fill byte
            i += 1
            continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:   # markers without a length field
            i += 2
            continue
        if marker in (0xD9, 0xDA):    # end of image / start of scan before any frame header
            return None
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2:
            return None
        if marker in _SOF_MARKERS:
            if i + 9 > n:
                return None
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    return None


def validate_upload(data: bytes, *, max_bytes: int, max_pixels: int) -> FileInfo:
    if not data:
        raise UploadRejected("empty_file", "The file is empty.")
    if len(data) > max_bytes:
        raise UploadRejected("file_too_large", f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    kind = sniff(data)
    if kind is None:
        raise UploadRejected("unsupported_type", "Only JPEG, PNG or PDF files are accepted.")
    if kind == "pdf":
        if _PDF_ACTIVE.search(data):
            raise UploadRejected("unsafe_pdf", "This PDF contains active content and cannot be accepted.")
        return FileInfo("pdf", "pdf", "application/pdf", None, None)
    dims = _png_dimensions(data) if kind == "png" else _jpeg_dimensions(data)
    if dims is None or dims[0] < 1 or dims[1] < 1:
        raise UploadRejected("unreadable_image", "This image could not be read.")
    if dims[0] * dims[1] > max_pixels:
        raise UploadRejected("image_too_large", "This image has too many pixels. Please upload a smaller photo.")
    ext, content_type = ("jpg", "image/jpeg") if kind == "jpeg" else ("png", "image/png")
    return FileInfo(kind, ext, content_type, dims[0], dims[1])
